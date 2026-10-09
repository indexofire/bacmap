"""cgMLST Hamming distance matrix + MST/NJ tree builder for cohort analysis.

Computes pairwise allele distances between cgMLST profiles and renders a tree
representation suitable for cohort reports (``cgmlst_cohort`` ANALYSIS payload,
downstream of the cohort rules in ``workflows/bacmap/rules/cgmlst.smk``). The
output format mirrors the format-agnostic cohort-summary generator
``workflows/bacmap/scripts/generate_snp_summary.py`` (Newick + pairwise
distances -> JSON), NOT ``generate_snp_matrix.py`` (VCF-specific).

Distance definition (EnteroBase HierCC convention, Zhou 2020):
    d(A, B) = number of loci where BOTH A and B have a non-None allele call
              AND the calls differ. Loci missing on either side (None) are
              excluded from the comparison (not counted as differences, and
              not counted as matches either).

Tree algorithms:
    * ``method="nj"`` (default) -- pure-Python neighbour-joining per Saitou &
      Nei (1987), no external dependency beyond scipy/biopython. Produces an
      unrooted bifurcating tree rendered as Newick. Negative branch lengths
      are clamped to zero (standard practice; e.g. FastTree does the same).
    * ``method="mst"`` -- minimum spanning tree via
      ``scipy.sparse.csgraph.minimum_spanning_tree`` over the complete
      Hamming-weighted graph (Prim's algorithm). Renders the MST as Newick
      by rooting at the first sample and emitting children with their edge
      weights. MST is the canonical layout for cgMLST clustering visualisation
      (GrapeTree default rendering; Zhou 2020).

Both methods produce Newick that round-trips through ``Bio.Phylo.parse``
(biopython 1.87+). The MST path requires scipy (confirmed as a transitive
dependency of sourmash in the pixi env; also available in the dev venv).

References:
    * Saitou, N. & Nei, M. (1987). The neighbor-joining method: a new method
      for reconstructing phylogenetic trees. Mol Biol Evol 4(4):406-425.
    * Zhou, Z., Alikhan, N. F., Sergeant, M. J., et al. (2020). The
      EnteroBase user's guide: comparative bacterial genomics and
      visualization with HierCC clustering. Genome Res 30:1-14.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from io import StringIO

from Bio.Phylo._io import parse as parse_newick
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import minimum_spanning_tree

from .cgmlst_types import CgmlstProfile


@dataclass
class DistanceMatrix:
    """Symmetric pairwise Hamming distance matrix.

    Attributes:
        samples: Sample IDs in the order they appeared in the input list.
        distances: Nested dict ``distances[a][b]`` -> Hamming allele distance.
            Always symmetric (``distances[a][b] == distances[b][a]``) with a
            zero diagonal (``distances[a][a] == 0``). Both directions are
            populated so callers can look up either way.
    """

    samples: list[str]
    distances: dict[str, dict[str, int]] = field(default_factory=dict)


def _hamming(a: dict[str, int | None], b: dict[str, int | None]) -> int:
    """Hamming distance: count loci where both called AND differ.

    Iterates the smaller dict for symmetry-safety, but in practice the two
    dicts share the same locus keys (same cgMLST scheme).
    """
    diff = 0
    for locus, a_allele in a.items():
        b_allele = b.get(locus)
        if a_allele is not None and b_allele is not None and a_allele != b_allele:
            diff += 1
    return diff


def distance_matrix(profiles: list[CgmlstProfile]) -> DistanceMatrix:
    """Build a pairwise Hamming distance matrix from cgMLST profiles.

    The distance between two profiles is the count of loci where both have a
    non-None allele call AND the alleles differ (EnteroBase HierCC convention;
    loci missing on either side are excluded). The returned matrix is symmetric
    with a zero diagonal. The input profiles are not mutated.

    Args:
        profiles: One or more ``CgmlstProfile`` objects (typically the output
            of ``parse_cgmlst_profiles``).

    Returns:
        A populated ``DistanceMatrix``.

    Raises:
        ValueError: If ``profiles`` is empty.
    """
    if not profiles:
        raise ValueError("distance_matrix requires at least one profile")

    samples = [p.sample_id for p in profiles]

    distances: dict[str, dict[str, int]] = {s1: {s2: 0 for s2 in samples} for s1 in samples}

    for i, pi in enumerate(profiles):
        ai = pi.alleles
        for j in range(i + 1, len(profiles)):
            pj = profiles[j]
            d = _hamming(ai, pj.alleles)
            distances[samples[i]][samples[j]] = d
            distances[samples[j]][samples[i]] = d

    return DistanceMatrix(samples=samples, distances=distances)


def _mst_to_newick(matrix: DistanceMatrix) -> str:
    """Build a minimum spanning tree via scipy and render as Newick.

    Uses Prim's algorithm (``scipy.sparse.csgraph.minimum_spanning_tree``) on
    the complete Hamming-weighted graph. Zero-distance edges are bumped to a
    small epsilon internally so scipy treats them as real edges (scipy's MST
    treats exact-zero entries as missing), then restored to zero when emitted.
    The tree is rooted at ``samples[0]`` and rendered as a possibly-multifurc
    -ating Newick with sample names on both leaves and internal branching
    points (which is how GrapeTree-style MSTs are typically displayed).
    """
    samples = matrix.samples
    n = len(samples)

    if n == 1:
        return f"{samples[0]};"

    rows: list[int] = []
    cols: list[int] = []
    data: list[float] = []
    for i in range(n):
        for j in range(i + 1, n):
            d = matrix.distances[samples[i]][samples[j]]
            # scipy MST treats 0.0 as "no edge"; bump true-zero to epsilon so
            # identical samples still get connected. Restored to 0 on output.
            w = float(d) if d > 0 else 1e-6
            rows.extend((i, j))
            cols.extend((j, i))
            data.extend((w, w))

    graph = csr_matrix((data, (rows, cols)), shape=(n, n))
    mst_arr = minimum_spanning_tree(graph).toarray()

    # Build undirected adjacency from the upper-triangular MST output, but
    # always read the original integer weight from `matrix.distances` so the
    # epsilon-bump is invisible to downstream consumers.
    adj: list[list[tuple[int, float]]] = [[] for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if mst_arr[i][j] != 0:
                w = float(matrix.distances[samples[i]][samples[j]])
                adj[i].append((j, w))
                adj[j].append((i, w))

    visited = [False] * n

    def dfs(node: int) -> str:
        visited[node] = True
        child_strings: list[str] = []
        for child, weight in adj[node]:
            if not visited[child]:
                subtree = dfs(child)
                child_strings.append(f"{subtree}:{weight:g}")
        name = samples[node]
        if not child_strings:
            return name
        return f"({','.join(child_strings)}){name}"

    return dfs(0) + ";"


def _nj_to_newick(matrix: DistanceMatrix) -> str:
    """Pure-Python neighbour-joining (Saitou & Nei 1987).

    Produces an unrooted bifurcating tree. Branch-length formulas:

        delta      = (r[i] - r[j]) / (m - 2)
        branch_i   = 0.5 * d(i,j) + 0.5 * delta
        branch_j   = d(i,j) - branch_i
        d(new, k)  = 0.5 * (d(i,k) + d(j,k) - d(i,j))

    where ``r[i]`` is the sum of distances from ``i`` to all other active
    nodes and ``m`` is the current active-node count. Negative branch lengths
    are clamped to zero (FastTree-style). On termination the two remaining
    nodes are joined with the residual distance split evenly.
    """
    samples = matrix.samples
    n = len(samples)

    if n == 1:
        return f"{samples[0]};"
    if n == 2:
        d = matrix.distances[samples[0]][samples[1]]
        half = d / 2.0
        return f"({samples[0]}:{half:g},{samples[1]}:{half:g});"

    # labels[k] is either a sample name (leaf) or a partial Newick subtree
    # string without the trailing ";" (internal). Indices grow as joins occur.
    labels: list[str] = list(samples)

    # Dense working distance matrix indexed by node id. Removed nodes have
    # their entries deleted to keep the structure tidy.
    D: dict[int, dict[int, float]] = {}
    for i in range(n):
        D[i] = {}
        for j in range(n):
            if i != j:
                D[i][j] = float(matrix.distances[samples[i]][samples[j]])

    next_id = n
    active: list[int] = list(range(n))

    while len(active) > 2:
        m = len(active)
        r = {i: sum(D[i][j] for j in active if j != i) for i in active}

        best_q: float | None = None
        best_pair: tuple[int, int] | None = None
        for a_idx in range(len(active)):
            for b_idx in range(a_idx + 1, len(active)):
                i_node, j_node = active[a_idx], active[b_idx]
                q = (m - 2) * D[i_node][j_node] - r[i_node] - r[j_node]
                if best_q is None or q < best_q:
                    best_q = q
                    best_pair = (i_node, j_node)
        assert best_pair is not None
        i_node, j_node = best_pair

        d_ij = D[i_node][j_node]
        delta = (r[i_node] - r[j_node]) / (m - 2)
        b_i = max(0.0, 0.5 * d_ij + 0.5 * delta)
        b_j = max(0.0, d_ij - b_i)

        new_id = next_id
        next_id += 1
        labels.append(f"({labels[i_node]}:{b_i:g},{labels[j_node]}:{b_j:g})")

        D[new_id] = {}
        for k in active:
            if k == i_node or k == j_node:
                continue
            new_d = max(0.0, 0.5 * (D[i_node][k] + D[j_node][k] - d_ij))
            D[new_id][k] = new_d
            D[k][new_id] = new_d

        active.remove(i_node)
        active.remove(j_node)
        active.append(new_id)
        for k in list(D.keys()):
            D[k].pop(i_node, None)
            D[k].pop(j_node, None)
        D.pop(i_node, None)
        D.pop(j_node, None)

    assert len(active) == 2
    a_node, b_node = active[0], active[1]
    half = D[a_node][b_node] / 2.0
    return f"({labels[a_node]}:{half:g},{labels[b_node]}:{half:g});"


def build_tree(matrix: DistanceMatrix, method: str = "nj") -> str:
    """Build a Newick tree from a Hamming distance matrix.

    Args:
        matrix: A ``DistanceMatrix`` produced by ``distance_matrix()``.
        method: ``"nj"`` (default; pure-Python neighbour-joining per Saitou &
            Nei 1987) or ``"mst"`` (minimum spanning tree via scipy's
            ``minimum_spanning_tree`` / Prim's algorithm).

    Returns:
        A Newick-format string ending in ``;``. For a single-sample matrix a
        trivial ``"sample;"`` Newick is returned.

    Raises:
        ValueError: If ``method`` is unknown, the matrix has no samples, or
            the produced Newick fails ``Bio.Phylo.parse`` validation.
    """
    if not matrix.samples:
        raise ValueError("build_tree requires a non-empty DistanceMatrix")

    if method == "nj":
        newick = _nj_to_newick(matrix)
    elif method == "mst":
        newick = _mst_to_newick(matrix)
    else:
        raise ValueError(f"unknown tree method: {method!r} (use 'nj' or 'mst')")

    # Self-validate: every produced tree must round-trip through Bio.Phylo.
    try:
        trees = list(parse_newick(StringIO(newick), "newick"))  # type: ignore[no-untyped-call]
    except Exception as e:  # pragma: no cover - defensive guard
        raise ValueError(f"produced invalid Newick {newick!r}: {e}") from e
    if not trees:
        raise ValueError(f"Bio.Phylo parsed zero trees from {newick!r}")

    return newick
