#! /usr/bin/env python3
import os
import re

def rename_fastq(directory='.'):
    """
    智能重命名FASTQ文件，支持复杂样本名称
    核心逻辑：
    1. 第一个下划线前的内容作为样本ID（支持字母数字）
    2. 提取最后一个出现的R1/R2/1/2作为配对标识
    3. 保留原文件扩展名
    """
    pattern = re.compile(
        r'^([A-Za-z0-9-]+)'         # 样本ID（字母数字和-组合）
        r'(?:_.+?)*'                # 中间任意数量下划线分段
        r'_([Rr]?[12])'             # 配对标识（强制最后出现）
        r'(?:_.+?)*'                # 后续可能存在的其他内容
        r'\.fastq\.gz$', 
        flags=re.IGNORECASE
    )

    for filename in os.listdir(directory):
        # 跳过非目标文件
        if not filename.lower().endswith('.fastq.gz'):
            continue
        
        if match := pattern.match(filename):
            sample_id = match.group(1)
            pair_id = match.group(2).upper()  # 标准化为R1/R2

            new_name = f"{sample_id}_{pair_id}.fastq.gz"
            if new_name == filename:
                print(f"警告：目标文件 {new_name} 已符合命名规则，跳过重命名环节 {filename}")
                continue
            old_path = os.path.join(directory, filename)
            new_path = os.path.join(directory, new_name)

            # 冲突检测与处理
            if os.path.exists(new_path):
                print(f"警告：目标文件 {new_name} 已存在， 请确认文件是否重复或者命名是否正确 {filename}")
                continue
            
            try:
                os.rename(old_path, new_path)
            except Exception as e:
                print(f"重命名失败：{filename} → {str(e)}")
            print(f"重命名：{filename[:30]:<30} → {new_name}")

if __name__ == '__main__':
    rename_fastq(".")  # 可指定目录如：rename_files("/your/data/path")
