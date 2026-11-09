#!/bin/bash
# 脚本: extract_cps.sh
# 功能: 从 GFF 文件中提取指定基因的 CDS 区间，判断是否在同一个 contig 上
# 输出: CSV 格式（逗号分隔）
# 用法: ./extract_cps.sh <gene_A> <gene_B> file1.gff [file2.gff ...]
# 示例: ./extract_cps.sh kpsS kpsM *.gff > results.tsv
# 依赖: GNU parallel (apt install parallel)

if [ $# -lt 3 ]; then
    echo "用法: $0 <gene_A> <gene_B> file1.gff [file2.gff ...]" >&2
    exit 1
fi

GENE_A="$1"
GENE_B="$2"
shift 2

# 过滤出存在的文件
valid_files=()
for f in "$@"; do
    [ -f "$f" ] && valid_files+=("$f")
done

if [ ${#valid_files[@]} -eq 0 ]; then
    echo "错误: 没有有效的 GFF 文件" >&2
    exit 1
fi

export GENE_A GENE_B

# 单文件处理函数，由 parallel 调用
process_one() {
    local gff="$1"
    local genome_name
    genome_name=$(basename "${gff%.gff}")

    LC_ALL=C awk -F'\t' -v ga="$GENE_A" -v gb="$GENE_B" -v genome_name="$genome_name" '
    function flush(cur_name,    i, a_cstr, a_sstr, a_estr, b_cstr, b_sstr, b_estr, status) {
        a_cstr = ""; a_sstr = ""; a_estr = ""
        for (i = 1; i <= cnt_a; i++) {
            if (i > 1) { a_cstr=a_cstr ";"; a_sstr=a_sstr ";"; a_estr=a_estr ";" }
            a_cstr = a_cstr a_contig[i]
            a_sstr = a_sstr a_start[i]
            a_estr = a_estr a_end[i]
        }
        b_cstr = ""; b_sstr = ""; b_estr = ""
        for (i = 1; i <= cnt_b; i++) {
            if (i > 1) { b_cstr=b_cstr ";"; b_sstr=b_sstr ";"; b_estr=b_estr ";" }
            b_cstr = b_cstr b_contig[i]
            b_sstr = b_sstr b_start[i]
            b_estr = b_estr b_end[i]
        }

        if (cnt_a > 1 || cnt_b > 1) {
            print cur_name, "ambiguous", ga, cnt_a, a_cstr, a_sstr, a_estr, gb, cnt_b, b_cstr, b_sstr, b_estr
        } else if (cnt_a == 1 && cnt_b == 1) {
            status = (a_contig[1] == b_contig[1]) ? "complete" : "fragment"
            print cur_name, status, ga, cnt_a, a_cstr, a_sstr, a_estr, gb, cnt_b, b_cstr, b_sstr, b_estr
        } else {
            print cur_name, "missing", ga, cnt_a, (cnt_a ? a_cstr : "none"), (cnt_a ? a_sstr : "0"), (cnt_a ? a_estr : "0"), gb, cnt_b, (cnt_b ? b_cstr : "none"), (cnt_b ? b_sstr : "0"), (cnt_b ? b_estr : "0")
        }
    }

    BEGIN {
        OFS = ","
        ka1 = ";gene=" ga ";"; ka2 = ";Name=" ga ";"
        ka3 = ";ID=" ga ";"   ; ka4 = ";locus_tag=" ga ";"
        kb1 = ";gene=" gb ";"; kb2 = ";Name=" gb ";"
        kb3 = ";ID=" gb ";"   ; kb4 = ";locus_tag=" gb ";"
    }

    $3 == "CDS" {
        safe = $9 ";"
        if (index(safe,ka1) || index(safe,ka2) || index(safe,ka3) || index(safe,ka4)) {
            cnt_a++
            a_contig[cnt_a] = $1
            a_start[cnt_a]  = $4
            a_end[cnt_a]    = $5
        }
        if (index(safe,kb1) || index(safe,kb2) || index(safe,kb3) || index(safe,kb4)) {
            cnt_b++
            b_contig[cnt_b] = $1
            b_start[cnt_b]  = $4
            b_end[cnt_b]    = $5
        }
    }

    END {
        if (cnt_a > 0 || cnt_b > 0) flush(genome_name)
    }' "$gff"
}

export -f process_one

# --keep-order 保证输出顺序与输入一致
# -j $(nproc) 使用所有可用 CPU 核心
printf '%s\n' "${valid_files[@]}" | \
    parallel --keep-order -j "$(nproc)" process_one {}
