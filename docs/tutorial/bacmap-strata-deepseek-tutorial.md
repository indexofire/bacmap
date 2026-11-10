# Tutorial: running bacmap end-to-end with a local Strata + DeepSeek backend

A hands-on, hardware-specific walkthrough (Chinese, 335 lines) for driving bacmap's
full loop — batch genome analysis (`analyze`), data mining (`mine`), and paper
writing (`write`) — on a personal Linux workstation, using
[Strata](https://strata.ai) with a quantised DeepSeek model as the local LLM
backend (example hardware: RTX 5060 Ti 16 GB + 64 GB RAM, ≥300 GB disk).

The full text is maintained in Chinese — use the language switcher at the top of
this page to read it. In short: run Strata with a quantised DeepSeek model on a
personal workstation as bacmap's LLM backend, then walk a full
「analyse → mine → write」 flow over ~100 NCBI *Salmonella* genomes.

Key stages covered: Strata install & model download → bacmap pixi environment &
config → NCBI datasets download of ~100 *Salmonella* genomes → batch `analyze`
plans → `mine` sandbox mining with human sign-off → research sessions & submission
packages → `write` task with citation gates.
