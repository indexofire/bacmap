#! /usr/bin/env python3
import os
import re
import argparse

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

def main():
    # 配置命令行参数解析
    parser = argparse.ArgumentParser(
        description="智能重命名FASTQ文件，支持复杂样本名称",
        epilog="示例：%(prog)s -d /data/fastq_files"
    )
    parser.add_argument('-d', '--directory', 
                        default='.', 
                        help="指定包含FASTQ文件的目录（默认当前目录）")
    parser.add_argument('-o', '--output',
                        default='.',
                        help="指定输出目录（默认当前目录）")
    args = parser.parse_args()

    # 验证目录有效性
    if not os.path.isdir(args.directory):
        print(f"错误：指定的路径不是有效目录 ({args.directory})")
        return

    rename_fastq(args.directory)

if __name__ == '__main__':
    main()