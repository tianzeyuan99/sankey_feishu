#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""多sheet长格式Excel转换为宽格式"""

import pandas as pd
import os
from typing import Optional

def convert_multi_sheet_to_wide_format(excel_path: str, output_path: Optional[str] = None) -> str:
    """
    将多sheet长格式Excel转换为单sheet宽格式
    
    输入格式（每个sheet）:
        阶段      项目名称    费用  说明
        25年预算  OA         250   A
    
    输出格式:
        时间列   OA   OA_说明  海能集成  海能集成_说明  ...  总预算
        25年预算  250   A      250       B          ...  1000
    
    Returns:
        转换后的文件路径
    """
    # 读取所有sheet
    excel_data = pd.read_excel(excel_path, sheet_name=None, header=0)
    
    all_wide_data = []
    
    for sheet_name, df in excel_data.items():
        # 检查必需的列
        required_cols = ['阶段', '项目名称', '费用', '说明']
        if not all(col in df.columns for col in required_cols):
            continue
        
        # 按阶段分组
        for phase, group in df.groupby('阶段'):
            # 创建宽格式行
            row_data = {'时间列': f"{sheet_name}_{phase}"}
            
            # 获取所有项目
            projects = group['项目名称'].unique()
            
            # 为每个项目添加费用列和说明列
            project_totals = []  # 用于验证总预算
            for project in projects:
                project_data = group[group['项目名称'] == project].iloc[0]
                fee = project_data['费用']
                desc = project_data['说明'] if pd.notnull(project_data['说明']) else ''
                
                # 项目费用列：保留8位小数（预算金额要严谨）
                if pd.notnull(fee):
                    fee_value = round(float(fee), 8)
                    project_totals.append(fee_value)
                else:
                    fee_value = 0.0
                    project_totals.append(0.0)
                row_data[project] = fee_value
                # 项目说明列
                row_data[f"{project}_说明"] = str(desc) if desc else ''
            
            # 计算总预算：所有项目费用相加，保留8位小数
            calculated_total = round(sum(project_totals), 8)
            # 验证：从原始数据计算的总和
            original_sum = round(group['费用'].sum(), 8)
            # 如果两者不一致，记录警告但使用计算值（更准确）
            if abs(calculated_total - original_sum) > 0.00000001:  # 允许浮点数误差
                print(f"⚠️  警告: Sheet '{sheet_name}' 阶段 '{phase}' 总预算计算不一致: 计算值={calculated_total}, 原始值={original_sum}")
            row_data['总预算'] = calculated_total
            
            all_wide_data.append(row_data)
    
    if not all_wide_data:
        raise ValueError("没有找到有效的数据")
    
    # 转换为DataFrame
    wide_df = pd.DataFrame(all_wide_data)
    
    # 确保列顺序：时间列、项目1、项目1说明、项目2、项目2说明、...、总预算
    project_cols = []
    desc_cols = []
    seen_projects = set()
    
    # 从第一个sheet的第一个阶段获取项目顺序（保持原始表格顺序）
    first_sheet_name = list(excel_data.keys())[0]
    first_df = excel_data[first_sheet_name]
    first_phase = first_df['阶段'].iloc[0] if '阶段' in first_df.columns else None
    
    if first_phase:
        first_phase_data = first_df[first_df['阶段'] == first_phase]
        for _, row in first_phase_data.iterrows():
            project = row['项目名称']
            if project not in seen_projects:
                project_cols.append(project)
                seen_projects.add(project)
    
    # 如果还有未包含的项目
    for col in wide_df.columns:
        if col == '时间列' or col == '总预算':
            continue
        if col.endswith('_说明'):
            desc_cols.append(col)
        else:
            if col not in project_cols:
                project_cols.append(col)
    
    # 构建列顺序
    ordered_cols = ['时间列']
    for project in project_cols:
        ordered_cols.append(project)
        desc_col = f"{project}_说明"
        if desc_col in desc_cols:
            ordered_cols.append(desc_col)
    ordered_cols.append('总预算')
    
    # 只保留存在的列
    ordered_cols = [col for col in ordered_cols if col in wide_df.columns]
    
    # 重新排列列
    wide_df = wide_df[ordered_cols]
    
    # 保存转换后的文件
    if output_path is None:
        base_name = os.path.splitext(os.path.basename(excel_path))[0]
        dir_name = os.path.dirname(excel_path)
        output_path = os.path.join(dir_name, f"{base_name}_宽格式.xlsx")
    
    wide_df.to_excel(output_path, index=False, engine='openpyxl')
    return output_path

