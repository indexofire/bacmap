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
  'gvixb.mst/v1': validateMst,
};

export function validateData(schema, data) {
  const validator = SCHEMAS[schema];
  if (!validator) return { ok: false, errors: [`未注册的 schema：${schema}`] };
  const errors = validator(data);
  return { ok: errors.length === 0, errors };
}
