#! /usr/bin/env python3
import os
import re
import argparse
import subprocess
from pathlib import Path


def rename_fastq(directory):
    """
    智能重命名FASTQ文件，支持复杂样本名称和多种扩展名
    核心逻辑：
    1. 使用第一个下划线前的内容作为样本ID
    2. 提取最后一个出现的配对标识（支持R1/R2/1/2）
    3. 统一扩展名为.fastq.gz
    4. 自动转换数字标识为R前缀格式
    """
    for filename in os.listdir(directory):
        # 检查扩展名（支持.fq.gz和.fastq.gz）
        if not filename.lower().endswith(('.fastq.gz', '.fq.gz')):
            continue
        
        # 提取样本ID（第一个下划线前的内容）
        sample_id = filename.split('_', 1)[0]

        # 查找所有可能的配对标识
        matches = re.findall(r'_([Rr]?[12])[\W_]*', filename, flags=re.IGNORECASE)
        if not matches:
            print(f"警告：未找到配对标识，跳过文件 {filename}")
            continue

        # 处理配对标识（取最后一个并标准化为R1/R2）
        last_match = matches[-1].upper()
        if last_match.startswith('R'):
            pair_id = last_match
        else:
            pair_id = f"R{last_match}"

        # 构建新文件名并统一扩展名
        new_name = f"{sample_id}_{pair_id}.fastq.gz"
        
        # 跳过无需修改的文件
        if new_name == filename:
            print(f"提示：文件 {filename} 已符合规范，无需修改")
            continue

        # 处理文件路径
        old_path = os.path.join(directory, filename)
        new_path = os.path.join(directory, new_name)

        # 冲突检测
        if os.path.exists(new_path):
            print(f"错误：目标文件 {new_name} 已存在，无法重命名 {filename}")
            continue

        # 执行重命名
        try:
            os.rename(old_path, new_path)
            print(f"重命名成功：{filename} → {new_name}")
        except Exception as e:
            print(f"错误：重命名 {filename} 失败，原因：{str(e)}")

def validate_fastq_pairs(directory):
    """
    验证目录中的完整fastq文件配对
    返回格式：{样本ID: {'R1': 路径, 'R2': 路径}}
    """
    fastq_files = {}
    pattern = re.compile(r'^(.+)_(R[12])\.fastq\.gz$', re.IGNORECASE)
    
    for f in os.listdir(directory):
        if not f.lower().endswith('.fastq.gz'):
            continue
        if match := pattern.match(f):
            sample = match.group(1)
            pair = match.group(2).upper()
            fastq_files.setdefault(sample, {})[pair] = os.path.join(directory, f)

    # 验证配对完整性
    valid_samples = {}
    for sample, pairs in fastq_files.items():
        if len(pairs) == 2 and 'R1' in pairs and 'R2' in pairs:
            valid_samples[sample] = pairs
        else:
            print(f"警告：样本 {sample} 的fastq配对不完整，跳过处理")
    return valid_samples

def run_assembler(sample, fq_pairs, assembler, output_dir, threads):
    """执行基因组组装工具"""
    output_path = os.path.join(output_dir, sample)
    os.makedirs(output_path, exist_ok=True)

    assembler_commands = {
        'spades': [
            'spades.py',
            '-1', fq_pairs['R1'],
            '-2', fq_pairs['R2'],
            '-o', output_path,
            '--threads', str(threads),
            '--careful'
        ],
        'skesa': [
            'skesa',
            '--fastq', fq_pairs['R1'], fq_pairs['R2'],
            '--cores', str(threads),
            '--contigs_out', os.path.join(output_path, f'{sample}.fasta')
        ]
    }

    if assembler not in assembler_commands:
        raise ValueError(f"不支持的组装工具：{assembler}")

    print(f"\n正在使用 {assembler} 组装样本：{sample}")
    print("执行命令：", ' '.join(assembler_commands[assembler]))

    try:
        result = subprocess.run(
            assembler_commands[assembler],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )
        print(f"组装成功：{sample}\n输出目录：{output_path}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"组装失败：{sample}\n错误信息：{e.output}")
        return False

def main():
    parser = argparse.ArgumentParser(
        description="整合式基因组分析流程",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog="使用示例：\n"
               "  基本重命名：%(prog)s -d ./data\n"
               "  完整流程：%(prog)s -d ./data --run-assembler --assembler spades\n"
               "  自定义参数：%(prog)s -d ./data -a skesa -o ./results -t 8"
    )
    
    # 核心参数
    parser.add_argument('-d', '--directory',
                        default='.',
                        help="输入目录路径（默认当前目录）")
    
    # 组装参数组
    assembly_group = parser.add_argument_group('组装参数')
    assembly_group.add_argument('--run-assembler',
                                action='store_true',
                                help="启用组装流程")
    assembly_group.add_argument('-a', '--assembler',
                                choices=['spades', 'skesa'],
                                default='spades',
                                help="选择组装工具（默认：spades）")
    assembly_group.add_argument('-o', '--output-dir',
                                default='assembly_results',
                                help="组装结果输出目录（默认：assembly_results）")
    assembly_group.add_argument('-t', '--threads',
                                type=int,
                                default=4,
                                help="CPU线程数（默认：4）")

    args = parser.parse_args()

    # 路径验证
    if not os.path.isdir(args.directory):
        print(f"错误：输入目录不存在 {args.directory}")
        return

    # 执行重命名流程（集成之前的重命名逻辑）
    print("="*40)
    print("执行文件重命名流程...")
    # 此处应插入原有的rename_fastq函数实现
    rename_fastq(args.directory)  # 确保已包含之前的重命名函数

    # 如果启用组装流程
    if args.run_assembler:
        print("\n" + "="*40)
        print("启动基因组组装流程...")
        
        # 验证fastq文件
        samples = validate_fastq_pairs(args.directory)
        if not samples:
            print("错误：未找到有效的fastq文件配对")
            return

        # 准备输出目录
        Path(args.output_dir).mkdir(parents=True, exist_ok=True)

        # 执行组装
        success_count = 0
        for sample, pairs in samples.items():
            if run_assembler(sample, pairs, args.assembler, args.output_dir, args.threads):
                success_count += 1

        print(f"\n组装完成：成功 {success_count}/{len(samples)} 个样本")

if __name__ == '__main__':
    main()