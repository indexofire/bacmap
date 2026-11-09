# 本脚本主要是将NCBI下载的json数据进行提取，
# 来获得其中有意义信息。目前使用AI可能效果更好，但是Token
# 成本可能会大幅增加
import json
import csv

def extract_nested(data, path):
    # 原有递归提取逻辑
    keys = path.split('.')
    for key in keys:
        if isinstance(data, dict) and key in data:
            data = data[key]
        else:
            return None
    return data if data is not None else "NA"

def get_serotype(biosample_data):
    # 新增：专门提取serotype字段
    if "attributes" in biosample_data:
        for attr in biosample_data["attributes"]:
            #if attr.get("name") == "serotype" or attr.get("name") == "serovar":
            if "sero" in attr.get("name"):
                return attr.get("value", "NA")
    return "NA"

def get_srainfo(data):
    if "sample_ids" in data:
        for attr in data["sample_ids"]:
            if attr.get("db") == "SRA":
                return attr.get("value", "NA")
    return "NA"

with open('biosample.json', 'r') as f:
    data = json.load(f)

# 可以通过注释自行选择需要的字段
fields = [
    ("accession", "accession"),
    ("annotation_info.stats.gene_counts.non_coding", "nc_gene"),
    ("annotation_info.stats.gene_counts.protein_coding", "coding_gene"),
    ("annotation_info.stats.gene_counts.pseudogene", "pseudogene"),
    ("annotation_info.stats.gene_counts.total", "total_genes"),
    #("annotation_info.method", "annotation_method"),
    #("annotation_info.software_version", "annotation_version"),
    ("assembly_info.assembly_level", "assembly_level"),
    ("assembly_info.assembly_method", "assembly_method"),
    ("assembly_info.bioproject_accession", "bioproject_accession"),
    ("assembly_info.biosample.accession", "biosample_accession"),
    ("assembly_info.biosample.strain", "strain"),
    ("assembly_info.biosample.collection_date", "collection_date"),
    ("assembly_info.biosample.geo_loc_name", "geo_loc_name"),
    ("assembly_info.biosample.host", "host"),
    ("assembly_info.biosample.host_disease", "disease"),
    ("assembly_info.biosample.isolation_source", "isolation_source"),
    # 修改serotype提取方式
    ("_custom_serotype", "serotype"),  # 占位符，实际由自定义函数处理
    ("assembly_info.sequencing_tech", "platform"),
    ("assembly_stats.total_sequence_length", "genome_length"),
    ("assembly_stats.number_of_contigs", "contigs"),
    ("organism.organism_name", "organism_name"),
    # ANI 检查，部分数据是没有的
    ("average_nucleotide_identity.best_ani_match.ani", "ANI"),
    ("average_nucleotide_identity.best_ani_match.assembly_coverage", "ANI_assembly_coverage"),
    ("average_nucleotide_identity.best_ani_match.type_assembly_coverage", "ANI_type_assembly_coverage"),
    ("average_nucleotide_identity.match_status", "ANI_match_status"),
    ("average_nucleotide_identity.submitted_organism", "ANI_organism"),
    ("average_nucleotide_identity.submitted_species", "ANI_species"),
    # checkm 检查，很多数据是没有的
    ("checkm_info.completeness", "checkm_completeness"),
    ("checkm_info.completeness_percentile", "checkm_completeness_percentile"),
    ("checkm_info.contamination", "checkm_contamination"),
    ("current_accession", "current_accession"),
    ("paired_accession", "paried_accession"),
    ("source_database", "source_database"),
    ("wgs_info.wgs_project_accession", "wgs_accession"),
    ("_custom_SRA", "SRA")
]

rows = []
for report in data["reports"]:
    row = {}
    # 提取常规字段
    for path, col_name in fields:
        if path == "_custom_serotype":
            # 特殊处理serotype
            biosample_data = extract_nested(report, "assembly_info.biosample")
            row[col_name] = get_serotype(biosample_data) if biosample_data else "NA"
        elif path == '_custom_SRA':
            SRA_accession = extract_nested(report, "assembly_info.biosample")
            row[col_name] = get_srainfo(SRA_accession) if SRA_accession else "NA"
        else:
            row[col_name] = str(extract_nested(report, path)) if extract_nested(report, path) else "NA"
    rows.append(row)

# 写入TSV
with open('output_fixed.tsv', 'w', newline='', encoding='utf-8') as f:
    writer = csv.DictWriter(f, fieldnames=[col for _, col in fields], delimiter='\t')
    writer.writeheader()
    writer.writerows(rows)

print("转换完成！输出文件：output_fixed.tsv")
