/**
 * Dependency-free data contract validators.
 *
 * The runtime validates the minimum that makes a view safe to mount: the
 * declared schema, top-level collections, referenced IDs and coordinates. It
 * does not attempt to re-derive biology or reject scientifically unusual but
 * structurally valid host output.
 */
const isObject = value => !!value && typeof value === 'object' && !Array.isArray(value);
const isArray = value => Array.isArray(value);
const isFiniteNumber = value => typeof value === 'number' && Number.isFinite(value);
const isNonEmptyString = value => typeof value === 'string' && value.trim() !== '';

function checkCommon(data, schema) {
  const errors = [];
  if (!isObject(data)) return { errors: ['顶层必须是 JSON 对象'] };
  if (data.schema !== schema) errors.push(`schema 必须是 ${schema}，实际为 ${data.schema ?? '缺失'}`);
  if (data.demo !== undefined && typeof data.demo !== 'boolean') errors.push('demo 必须是布尔值');
  if (data.source !== undefined && typeof data.source !== 'string') errors.push('source 必须是字符串');
  return { errors };
}

function validateRecords(records, label, errors, validateOne) {
  if (!isArray(records)) {
    errors.push(`${label} 必须是数组`);
    return new Map();
  }
  const byId = new Map();
  records.forEach((record, index) => {
    if (!isObject(record)) {
      errors.push(`${label}[${index}] 必须是对象`);
      return;
    }
    if (!isNonEmptyString(record.id)) errors.push(`${label}[${index}].id 必须是非空字符串`);
    else if (byId.has(record.id)) errors.push(`${label} 存在重复 id：${record.id}`);
    else byId.set(record.id, record);
    validateOne?.(record, index, errors);
  });
  return byId;
}

function validateContigs(contigs, errors, label = 'contigs') {
  const byId = validateRecords(contigs, label, errors, (contig, index) => {
    if (!isFiniteNumber(contig.length) || contig.length < 0) errors.push(`${label}[${index}].length 必须 >= 0`);
    if (contig.gc !== undefined && !isFiniteNumber(contig.gc)) errors.push(`${label}[${index}].gc 必须是数字`);
  });
  if (byId.size === 0) errors.push(`${label} 不能为空`);
  return byId;
}

function validateFeatures(features, contigIds, errors) {
  if (features === undefined) return;
  if (!isArray(features)) {
    errors.push('features 必须是数组');
    return;
  }
  features.forEach((feature, index) => {
    if (!isObject(feature)) {
      errors.push(`features[${index}] 必须是对象`);
      return;
    }
    if (!isNonEmptyString(feature.id)) errors.push(`features[${index}].id 必须是非空字符串`);
    if (!contigIds.has(feature.contig)) errors.push(`features[${index}] 引用了未知 contig：${feature.contig}`);
    if (!isFiniteNumber(feature.start) || !isFiniteNumber(feature.end)) {
      errors.push(`features[${index}] 坐标必须是数字`);
    } else if (feature.end < feature.start) {
      errors.push(`features[${index}] end 必须 >= start`);
    }
  });
}

function validateAssembly(data) {
  const { errors } = checkCommon(data, 'gvixb.assembly/v1');
  if (!isObject(data)) return errors;
  const contigIds = validateContigs(data.contigs, errors);
  validateFeatures(data.features, contigIds, errors);
  if (data.total_bp !== undefined && !isFiniteNumber(data.total_bp)) errors.push('total_bp 必须是数字');
  return errors;
}

function validateAnnotatedGenome(data) {
  const { errors } = checkCommon(data, 'gvixb.annotated-genome/v1');
  if (!isObject(data)) return errors;
  const repliconIds = validateContigs(data.replicons, errors, 'replicons');
  validateFeatures(data.features, repliconIds, errors);
  if (data.categories !== undefined && !isArray(data.categories)) errors.push('categories 必须是数组');
  return errors;
}

function validatePhylogeny(data) {
  const { errors } = checkCommon(data, 'gvixb.phylogeny/v1');
  if (!isObject(data)) return errors;
  if (!isNonEmptyString(data.newick)) errors.push('newick 必须是非空字符串');
  if (data.metadata !== undefined && !isObject(data.metadata)) errors.push('metadata 必须是对象');
  if (data.samples !== undefined && !isArray(data.samples)) errors.push('samples 必须是数组');
  return errors;
}

const PHYLO_V2_KINDS = new Set(['inferred', 'mst_derived']);
const PHYLO_V2_ROOT_STATUS = new Set(['rooted', 'unrooted', 'unknown']);
const PHYLO_V2_ROOT_METHODS = new Set(['outgroup', 'midpoint', 'dated', 'inference']);
const PHYLO_V2_UNITS = new Set(['substitutions_per_site', 'snp', 'allele_differences', 'years', 'none', 'unknown']);
const PHYLO_V2_FIELD_TYPES = new Set(['categorical', 'numeric', 'date', 'text']);
const PHYLO_V2_FIELD_ROLES = new Set(['time', 'place', 'source', 'cluster']);
const PHYLO_V2_DISTANCE_UNITS = new Set(['snp', 'allele_differences', 'other']);

function validatePhylogenyV2(data) {
  const { errors } = checkCommon(data, 'gvixb.phylogeny/v2');
  if (!isObject(data)) return errors;

  const tree = data.tree;
  if (!isObject(tree)) {
    errors.push('tree 必须是对象');
  } else {
    if (!isNonEmptyString(tree.newick)) errors.push('tree.newick 必须是非空字符串');
    if (!PHYLO_V2_KINDS.has(tree.kind)) errors.push(`tree.kind 必须是 ${[...PHYLO_V2_KINDS].join(' | ')}`);
    if (!isObject(tree.root) || !PHYLO_V2_ROOT_STATUS.has(tree.root?.status)) {
      errors.push(`tree.root.status 必须是 ${[...PHYLO_V2_ROOT_STATUS].join(' | ')}`);
    } else {
      if (tree.root.method !== undefined && !PHYLO_V2_ROOT_METHODS.has(tree.root.method)) {
        errors.push(`tree.root.method 必须是 ${[...PHYLO_V2_ROOT_METHODS].join(' | ')}`);
      }
      if (tree.root.outgroup !== undefined && !(
        isArray(tree.root.outgroup) && tree.root.outgroup.every(isNonEmptyString)
      )) errors.push('tree.root.outgroup 必须是叶名字符串数组');
    }
    if (!isObject(tree.branch_length) || !PHYLO_V2_UNITS.has(tree.branch_length?.unit)) {
      errors.push(`tree.branch_length.unit 必须是 ${[...PHYLO_V2_UNITS].join(' | ')}`);
    }
    if (tree.support !== undefined) {
      if (!isObject(tree.support)
        || !isArray(tree.support.labels) || !tree.support.labels.length
        || !tree.support.labels.every(isNonEmptyString)) {
        errors.push('tree.support.labels 必须是非空字符串数组');
      } else if (![1, 100].includes(tree.support.scale)) {
        errors.push('tree.support.scale 必须是 1 或 100');
      }
    }
  }

  if (data.fields !== undefined) {
    if (!isArray(data.fields)) {
      errors.push('fields 必须是数组');
    } else {
      const keys = new Set();
      const primaryByRole = new Map();
      data.fields.forEach((field, index) => {
        if (!isObject(field)) {
          errors.push(`fields[${index}] 必须是对象`);
          return;
        }
        if (!isNonEmptyString(field.key)) errors.push(`fields[${index}].key 必须是非空字符串`);
        else if (keys.has(field.key)) errors.push(`fields 存在重复 key：${field.key}`);
        else keys.add(field.key);
        if (!PHYLO_V2_FIELD_TYPES.has(field.type)) {
          errors.push(`fields[${index}].type 必须是 ${[...PHYLO_V2_FIELD_TYPES].join(' | ')}`);
        }
        if (field.role !== undefined && !PHYLO_V2_FIELD_ROLES.has(field.role)) {
          errors.push(`fields[${index}].role 必须是 ${[...PHYLO_V2_FIELD_ROLES].join(' | ')}`);
        }
      });
      data.fields.forEach(field => {
        if (!isObject(field) || !field.role) return;
        if (field.primary === true) {
          if (primaryByRole.has(field.role)) errors.push(`role ${field.role} 最多一个 primary 字段`);
          else primaryByRole.set(field.role, field.key);
        }
      });
      const byKey = new Map(data.fields.filter(isObject).map(field => [field.key, field]));
      for (const field of data.fields) {
        if (!isObject(field) || field.parent === undefined) continue;
        const parent = byKey.get(field.parent);
        if (!parent) {
          errors.push(`fields.${field.key}.parent 引用了未知字段：${field.parent}`);
          continue;
        }
        if (parent.role !== field.role) errors.push(`fields.${field.key}.parent 必须引用同 role 的字段`);
        if (field.type !== 'categorical' || parent.type !== 'categorical') {
          errors.push(`fields.${field.key}.parent 层级两侧都必须是 categorical`);
        }
        const seen = new Set([field.key]);
        let cursor = parent;
        while (cursor?.parent !== undefined) {
          if (seen.has(cursor.key)) { errors.push(`fields 存在 parent 环：${[...seen, cursor.key].join(' → ')}`); break; }
          seen.add(cursor.key);
          cursor = byKey.get(cursor.parent);
        }
      }
    }
  }

  if (data.metadata !== undefined) {
    if (!isObject(data.metadata)) errors.push('metadata 必须是对象');
    else for (const [leaf, record] of Object.entries(data.metadata)) {
      if (!isObject(record)) errors.push(`metadata.${leaf} 必须是对象`);
    }
  }

  if (data.matrices !== undefined) {
    if (!isArray(data.matrices)) {
      errors.push('matrices 必须是数组');
    } else {
      const matrixIds = new Set();
      data.matrices.forEach((matrix, index) => {
        if (!isObject(matrix)) {
          errors.push(`matrices[${index}] 必须是对象`);
          return;
        }
        if (!isNonEmptyString(matrix.id)) errors.push(`matrices[${index}].id 必须是非空字符串`);
        else if (matrixIds.has(matrix.id)) errors.push(`matrices 存在重复 id：${matrix.id}`);
        else matrixIds.add(matrix.id);
        if (!isArray(matrix.columns)) {
          errors.push(`matrices[${index}].columns 必须是数组`);
          return;
        }
        const columnIds = new Set();
        matrix.columns.forEach((column, ci) => {
          if (!isObject(column) || !isNonEmptyString(column.id)) {
            errors.push(`matrices[${index}].columns[${ci}].id 必须是非空字符串`);
          } else if (columnIds.has(column.id)) {
            errors.push(`matrices[${index}].columns 存在重复 id：${column.id}`);
          } else columnIds.add(column.id);
        });
        if (!isObject(matrix.rows)) {
          errors.push(`matrices[${index}].rows 必须是对象`);
          return;
        }
        for (const [leaf, row] of Object.entries(matrix.rows)) {
          if (!isArray(row) || row.length !== matrix.columns.length) {
            errors.push(`matrices[${index}].rows.${leaf} 长度必须等于 columns 数（${matrix.columns.length}）`);
            continue;
          }
          row.forEach((value, vi) => {
            if (value !== 0 && value !== 1 && value !== null) {
              errors.push(`matrices[${index}].rows.${leaf}[${vi}] 只能是 0 / 1 / null`);
            }
          });
        }
      });
    }
  }

  if (data.distances !== undefined) {
    const distances = data.distances;
    if (!isObject(distances)) {
      errors.push('distances 必须是对象');
    } else {
      if (!PHYLO_V2_DISTANCE_UNITS.has(distances.unit)) {
        errors.push(`distances.unit 必须是 ${[...PHYLO_V2_DISTANCE_UNITS].join(' | ')}`);
      }
      if (!isArray(distances.samples) || distances.samples.some(sample => !isNonEmptyString(sample))) {
        errors.push('distances.samples 必须是字符串数组');
      } else if (new Set(distances.samples).size !== distances.samples.length) {
        errors.push('distances.samples 不得重复');
      }
      if (isArray(distances.samples) && isArray(distances.values)) {
        const expected = (distances.samples.length * (distances.samples.length - 1)) / 2;
        if (distances.values.length !== expected) {
          errors.push(`distances.values 长度必须是 n(n-1)/2 = ${expected}`);
        } else {
          distances.values.forEach((value, vi) => {
            if (value !== null && !(isFiniteNumber(value) && value >= 0)) {
              errors.push(`distances.values[${vi}] 必须是 null 或非负有限数`);
            }
          });
        }
      } else if (!isArray(distances.values)) {
        errors.push('distances.values 必须是数组');
      }
    }
  }

  if (data.clades !== undefined) {
    if (!isArray(data.clades)) {
      errors.push('clades 必须是数组');
    } else {
      const cladeIds = new Set();
      data.clades.forEach((clade, index) => {
        if (!isObject(clade)) {
          errors.push(`clades[${index}] 必须是对象`);
          return;
        }
        if (!isNonEmptyString(clade.id)) errors.push(`clades[${index}].id 必须是非空字符串`);
        else if (cladeIds.has(clade.id)) errors.push(`clades 存在重复 id：${clade.id}`);
        else cladeIds.add(clade.id);
        if (!isArray(clade.members) || !clade.members.length || !clade.members.every(isNonEmptyString)) {
          errors.push(`clades[${index}].members 必须是非空叶名数组`);
        }
      });
    }
  }

  if (data.summary !== undefined && !isObject(data.summary)) errors.push('summary 必须是对象');
  return errors;
}

function validateMst(data) {
  const { errors } = checkCommon(data, 'gvixb.mst/v1');
  if (!isObject(data)) return errors;
  const nodeIds = validateRecords(data.nodes, 'nodes', errors);
  if (nodeIds.size === 0) errors.push('nodes 不能为空');
  if (!isArray(data.edges)) {
    errors.push('edges 必须是数组');
    return errors;
  }
  data.edges.forEach((edge, index) => {
    if (!isObject(edge)) {
      errors.push(`edges[${index}] 必须是对象`);
      return;
    }
    if (!nodeIds.has(edge.source)) errors.push(`edges[${index}] 引用了未知 source：${edge.source}`);
    if (!nodeIds.has(edge.target)) errors.push(`edges[${index}] 引用了未知 target：${edge.target}`);
    if (!isFiniteNumber(edge.weight) || edge.weight < 0) errors.push(`edges[${index}].weight 必须是 >= 0 的数字`);
  });
  return errors;
}

export const SCHEMAS = {
  'gvixb.assembly/v1': validateAssembly,
  'gvixb.annotated-genome/v1': validateAnnotatedGenome,
  'gvixb.phylogeny/v1': validatePhylogeny,
  'gvixb.phylogeny/v2': validatePhylogenyV2,
  'gvixb.mst/v1': validateMst,
};

export function validateData(schema, data) {
  const validator = SCHEMAS[schema];
  if (!validator) return { ok: false, errors: [`未注册的 schema：${schema}`] };
  const errors = validator(data);
  return { ok: errors.length === 0, errors };
}
