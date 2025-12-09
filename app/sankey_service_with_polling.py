#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
项目内置：桑基图生成服务（与外部版本一致）
注：该模块被 app/main.py 以本地优先的方式导入
"""

# ... existing code ...
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
桑基图生成服务 - 带轮询功能
每2秒检查Excel文件变化，自动生成桑基图
"""

import os
import time
import pandas as pd
from pyecharts.charts import Sankey
from pyecharts import options as opts
import logging
from datetime import datetime
import hashlib
import threading
import signal
import sys
import requests
import urllib.parse

# 颜色调色板
COLOR_PALETTE = [
    "#5470c6", "#91cc75", "#fac858", "#ee6666", "#73c0de", "#3ba272",
    "#fc8452", "#9a60b4", "#ea7ccc", "#5d7092", "#6e9ef1", "#f6c555",
    "#ef6567", "#95d475", "#f7a35c", "#8085e9", "#f15c80", "#e4d354",
    "#2b908f", "#f45b5b"
]

class SankeyService:
    def __init__(self,
                 watch_dir="/home/cnooc/file/excel",
                 output_dir="/home/cnooc/file/sankey",
                 log_file="/home/cnooc/python_app/sankey_service.log",
                 poll_interval=2
                 ):
        
        self.watch_dir = watch_dir
        self.output_dir = output_dir
        self.poll_interval = poll_interval
        self.log_file = log_file  # 先赋值log_file
        self.running = False
        self.file_hashes = {}  # 记录文件哈希值，用于检测变化
        
        # 确保输出目录存在
        os.makedirs(output_dir, exist_ok=True)
        log_dir = os.path.dirname(log_file)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
        
        self.setup_logging()
        self.logger.info("桑基图服务初始化完成")
    
    def setup_logging(self):
        """设置日志"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(self.log_file),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)
    
    def get_file_hash(self, file_path):
        """计算文件哈希值"""
        try:
            with open(file_path, 'rb') as f:
                return hashlib.md5(f.read()).hexdigest()
        except:
            return None
    
    def find_xlsx_files(self):
        """查找Excel文件"""
        xlsx_files = []
        if os.path.exists(self.watch_dir):
            for file in os.listdir(self.watch_dir):
                if file.lower().endswith('.xlsx'):
                    xlsx_files.append(os.path.join(self.watch_dir, file))
        return xlsx_files

    def _is_edges_file(self, path):
        """快速判断是否为边表文件(包含source/target/value列)"""
        try:
            df = pd.read_excel(path, nrows=1)
            cols = set([c.strip() for c in df.columns.astype(str)])
            return {'source', 'target'}.issubset(cols) and (
                'value' in cols or 'Value' in cols or 'VALUE' in cols)
        except Exception:
            return False

    def _is_budget_file(self, path):
        """粗略判断是否为预算文件(第一列像时间，后续成对列)"""
        try:
            df = pd.read_excel(path, nrows=1)
            return 'source' not in df.columns and 'target' not in df.columns
        except Exception:
            return False
    
    def convert_budget_to_edges(self, budget_file_path):
        """将预算文件转换为边表文件"""
        try:
            import pandas as pd
            import re
            
            self.logger.info("开始转换预算文件为边表: {}".format(os.path.basename(budget_file_path)))
            
            # 读取预算文件
            budget_df = pd.read_excel(budget_file_path)
            
            # 按照固定模式识别列
            time_col = budget_df.columns[0]
            project_cols = [budget_df.columns[i] for i in range(1, len(budget_df.columns) - 1, 2)]
            description_cols = [budget_df.columns[i] for i in range(2, len(budget_df.columns) - 1, 2)]
            
            meetings = budget_df[time_col].dropna().tolist()
            
            version_aliases = {}
            meeting_aliases = ["初始", "第一次", "第二次", "第三次", "第四次", "第五次"]
            for i, meeting in enumerate(meetings):
                version_aliases[meeting] = meeting_aliases[i] if i < len(meeting_aliases) else f"第{i+1}次"
            
            project_to_description = {}
            for i, project_col in enumerate(project_cols):
                if i < len(description_cols):
                    project_to_description[project_col] = description_cols[i]
            
            chinese_numerals = ['一', '二', '三', '四', '五', '六', '七', '八', '九', '十']
            edges = []
            for project_col in project_cols:
                project_name = project_col
                project_values = {}
                for meeting in meetings:
                    value = budget_df[budget_df[time_col] == meeting][project_col].iloc[0]
                    project_values[meeting] = value if pd.notnull(value) else 0
                for i in range(len(meetings) - 1):
                    from_meeting = meetings[i]
                    to_meeting = meetings[i + 1]
                    from_alias = version_aliases.get(from_meeting, from_meeting)
                    to_alias = version_aliases.get(to_meeting, to_meeting)
                    from_value = project_values[from_meeting]
                    to_value = project_values[to_meeting]
                    main_flow = min(from_value, to_value)
                    if main_flow > 0:
                        from_time = from_meeting.split('(')[1].split(')')[0] if '(' in from_meeting else from_meeting
                        to_time = to_meeting.split('(')[1].split(')')[0] if '(' in to_meeting else to_meeting
                        source_node = f"{project_name}（{from_alias}：{from_time}）"
                        target_node = f"{project_name}（{to_alias}：{to_time}）"
                        edges.append({"source": source_node, "target": target_node, "value": main_flow})
                    if from_value > to_value:
                        excess = from_value - to_value
                        if excess > 0:
                            resource_pool = f"资源池{chinese_numerals[i] if i < len(chinese_numerals) else str(i+1)}"
                            from_time = from_meeting.split('(')[1].split(')')[0] if '(' in from_meeting else from_meeting
                            source_node = f"{project_name}（{from_alias}：{from_time}）"
                            edges.append({"source": source_node, "target": resource_pool, "value": excess})
                    elif to_value > from_value:
                        deficit = to_value - from_value
                        if deficit > 0:
                            resource_pool = f"资源池{chinese_numerals[i] if i < len(chinese_numerals) else str(i+1)}"
                            to_time = to_meeting.split('(')[1].split(')')[0] if '(' in to_meeting else to_meeting
                            target_node = f"{project_name}（{to_alias}：{to_time}）"
                            edges.append({"source": resource_pool, "target": target_node, "value": deficit})
            edges_df = pd.DataFrame(edges)
            # 按预算文件名命名边表：{预算文件名}_edges.xlsx
            budget_base = os.path.splitext(os.path.basename(budget_file_path))[0]
            edges_file_path = os.path.join(self.watch_dir, f"{budget_base}_edges.xlsx")
            edges_df.to_excel(edges_file_path, index=False)
            self.logger.info("成功转换预算文件为边表: {}, 边数: {}".format(os.path.basename(edges_file_path), len(edges_df)))
            return edges_file_path
        except Exception as e:
            self.logger.error("转换预算文件失败: {}".format(e))
            return None

    # 其余方法保持与外部版本一致

    def process_directory_once(self):
        xlsx_files = self.find_xlsx_files()
        if not xlsx_files:
            return False
        edges_file = None
        budget_file = None
        for p in xlsx_files:
            if self._is_edges_file(p):
                edges_file = p
            elif self._is_budget_file(p):
                budget_file = p
        if edges_file is None:
            for p in xlsx_files:
                name = os.path.basename(p).lower()
                if 'edge' in name or ('source' in name and 'target' in name):
                    edges_file = p
                    break
        if budget_file and not edges_file:
            self.logger.info("检测到预算文件，正在转换为边表...")
            edges_file = self.convert_budget_to_edges(budget_file)
            if not edges_file:
                self.logger.error("预算文件转换失败")
                return False
        if edges_file is None:
            self.logger.error("目录中未找到边表文件或预算文件")
            return False
        self.logger.info("检测到边表文件: {}".format(os.path.basename(edges_file)))
        if budget_file:
            self.logger.info("检测到预算文件: {}".format(os.path.basename(budget_file)))
        if budget_file:
            base_name = os.path.splitext(os.path.basename(budget_file))[0]
            out_name = f"{base_name}_桑基图.html"
        else:
            base_name = os.path.splitext(os.path.basename(edges_file))[0]
            out_name = f"sankey_{base_name}.html"
        out_path = os.path.join(self.output_dir, out_name)
        ok = self.generate_sankey_chart(edges_file, out_path, budget_file)
        return ok

    def extract_phases_from_nodes(self, nodes):
        phases = set()
        for node in nodes:
            if '（' in node and '）' in node:
                phase_part = node.split('（')[1].split('）')[0]
                if '：' in phase_part:
                    phase = phase_part.split('：')[0]
                else:
                    phase = phase_part
                phases.add(phase)
        return sorted(list(phases))

    def extract_projects_from_nodes(self, nodes):
        projects = set()
        for node in nodes:
            if '（' in node and '）' in node:
                # 处理带金额的节点名称：项目名（会议：时间） 金额：xxx
                project = node.split('（')[0]
                projects.add(project)
            elif not node.startswith('资源池'):
                # 如果不是资源池节点，可能是其他格式，尝试提取项目名
                # 如果节点名称包含"金额："，则提取前面的部分
                if ' 金额：' in node:
                    project = node.split(' 金额：')[0].split('（')[0]
                    if project:
                        projects.add(project)
        return sorted(list(projects))

    def load_project_descriptions(self, budget_file):
        if not os.path.exists(budget_file):
            return {}
        try:
            budget_df = pd.read_excel(budget_file)
            time_col = budget_df.columns[0]
            data_cols = budget_df.columns[1:-1]
            project_cols = []
            description_cols = []
            for i in range(0, len(data_cols), 2):
                if i < len(data_cols):
                    project_cols.append(data_cols[i])
                if i + 1 < len(data_cols):
                    description_cols.append(data_cols[i + 1])
            meetings = budget_df[time_col].dropna().tolist()
            meeting_mapping = {}
            meeting_aliases = ["初始", "第一次", "第二次", "第三次", "第四次", "第五次"]
            for i, meeting in enumerate(meetings):
                meeting_mapping[meeting] = meeting_aliases[i] if i < len(meeting_aliases) else f"第{i+1}次"
            node_descriptions = {}
            for meeting in meetings:
                simplified_meeting = meeting_mapping[meeting]
                for i, project_col in enumerate(project_cols):
                    project_name = project_col
                    description = ""
                    if i < len(description_cols):
                        desc_col = description_cols[i]
                        desc_value = budget_df[budget_df[time_col] == meeting][desc_col].iloc[0]
                        if pd.notnull(desc_value):
                            description = str(desc_value)
                    if description:
                        meeting_time = meeting.split('(')[1].split(')')[0] if '(' in meeting else meeting
                        node_name = f"{project_name}（{simplified_meeting}：{meeting_time}）"
                        node_descriptions[node_name] = description
            return node_descriptions
        except Exception as e:
            self.logger.error("读取预算文件时出错: {}".format(e))
            return {}

    def load_node_amounts(self, budget_file):
        """从预算文件加载每个节点的金额"""
        if not os.path.exists(budget_file):
            return {}
        try:
            budget_df = pd.read_excel(budget_file)
            time_col = budget_df.columns[0]
            project_cols = [budget_df.columns[i] for i in range(1, len(budget_df.columns) - 1, 2)]
            meetings = budget_df[time_col].dropna().tolist()
            meeting_mapping = {}
            meeting_aliases = ["初始", "第一次", "第二次", "第三次", "第四次", "第五次"]
            for i, meeting in enumerate(meetings):
                meeting_mapping[meeting] = meeting_aliases[i] if i < len(meeting_aliases) else f"第{i+1}次"
            node_amounts = {}
            for meeting in meetings:
                simplified_meeting = meeting_mapping[meeting]
                for project_col in project_cols:
                    project_name = project_col
                    value = budget_df[budget_df[time_col] == meeting][project_col].iloc[0]
                    amount = value if pd.notnull(value) else 0
                    meeting_time = meeting.split('(')[1].split(')')[0] if '(' in meeting else meeting
                    node_name = f"{project_name}（{simplified_meeting}：{meeting_time}）"
                    node_amounts[node_name] = float(amount)
            return node_amounts
        except Exception as e:
            self.logger.error("读取节点金额时出错: {}".format(e))
            return {}

    def compute_phase_totals(self, budget_file):
        """按会议读取"总预算"(最后一列)，返回 (别名, 会议名称, 总预算) 列表，用于标题下方展示"""
        if not os.path.exists(budget_file):
            return []
        try:
            budget_df = pd.read_excel(budget_file)
            time_col = budget_df.columns[0]
            total_col = budget_df.columns[-1]  # 最后一列：总预算

            meetings = budget_df[time_col].dropna().tolist()
            meeting_aliases = ["初始", "第一次", "第二次", "第三次", "第四次", "第五次"]
            phase_info = []  # [(alias, phase_name, total), ...]

            for i, meeting in enumerate(meetings):
                alias = meeting_aliases[i] if i < len(meeting_aliases) else f"第{i+1}次"
                # 会议名称：用括号内的时间说明；如果没有括号就用整串
                if "(" in str(meeting) and ")" in str(meeting):
                    phase_name = str(meeting).split("(", 1)[1].rsplit(")", 1)[0]
                else:
                    phase_name = str(meeting)

                row = budget_df[budget_df[time_col] == meeting]
                v = row[total_col].iloc[0]
                if pd.notnull(v):
                    try:
                        phase_info.append((alias, phase_name, float(v)))
                    except Exception:
                        continue
            return phase_info
        except Exception as e:
            self.logger.error("读取会议总预算(最后一列)时出错: {}".format(e))
            return []

    def create_html_with_popup(self, echarts_html: str, node_descriptions: dict) -> str:
        """
        兼容两种输出：
        1) 若 echarts_html 是完整 HTML（包含 <html>），直接在 </body> 前注入弹窗与脚本；
        2) 若是片段，则用外层模板包裹。
        """
        import json
        desc_json = json.dumps(node_descriptions, ensure_ascii=False)

        inject_html = """
    <div id="descriptionModal" class="modal">
        <div class="modal-content">
            <span class="close">&times;</span>
            <div class="modal-title" id="modalTitle">项目描述</div>
            <div class="modal-description" id="modalDescription"></div>
        </div>
    </div>
    <style>
        #descriptionModal { display:none; position:fixed; z-index:1000; left:0; top:0; width:100%; height:100%; background:rgba(0,0,0,0.5); }
        .modal-content { background:#fff; margin:5% auto; padding:20px; border-radius:8px; width:80%; max-width:600px; box-shadow:0 4px 20px rgba(0,0,0,.3); position:relative; }
        .close { color:#aaa; position:absolute; right:15px; top:10px; font-size:28px; font-weight:bold; cursor:pointer; }
        .close:hover{ color:#000; }
        .modal-title { font-size:18px; font-weight:bold; margin-bottom:12px; color:#333; border-bottom:2px solid #4CAF50; padding-bottom:8px; }
        .modal-description { font-size:14px; line-height:1.6; color:#555; white-space:pre-line; }
        .no-description { color:#999; font-style:italic; }
    </style>
    <script>
        (function() {
            const NODE_DESCRIPTIONS = {DESC_JSON};
            function bind() {
                if (!window.echarts) return false;
                const all = document.querySelectorAll('div, canvas');
                let chart = null;
                for (const el of all) {
                    if (!el.id) continue;
                    try {
                        const inst = echarts.getInstanceByDom(el);
                        if (inst) { chart = inst; break; }
                    } catch(e) {}
                }
                if (!chart) return false;

                const modal = document.getElementById('descriptionModal');
                const title = document.getElementById('modalTitle');
                const body  = document.getElementById('modalDescription');
                const closeBtn = document.querySelector('#descriptionModal .close');

                function show(name) {
                    const desc = NODE_DESCRIPTIONS[name];
                    title.textContent = name || '未知节点';
                    if (desc) { body.textContent = desc; body.className = 'modal-description'; }
                    else { body.textContent = '暂无节点描述信息'; body.className = 'modal-description no-description'; }
                    modal.style.display = 'block';
                }
                function hide() { modal.style.display = 'none'; }

                closeBtn.onclick = hide;
                window.addEventListener('click', (e) => { if (e.target === modal) hide(); });
                window.addEventListener('keydown', (e) => { if (e.key === 'Escape') hide(); });

                chart.off('click');
                chart.on('click', function(params) {
                    if (params && params.componentType === 'series' && params.dataType === 'node') {
                        show((params.data && (params.data.name || params.name)) || params.name);
                    }
                });
                return true;
            }
            let tries = 0;
            const timer = setInterval(function() {
                tries += 1;
                if (bind() || tries >= 10) clearInterval(timer);
            }, 300);
        })();
    </script>
""".replace("{DESC_JSON}", desc_json)

        lower = echarts_html.lower()
        if "<html" in lower and "</body>" in lower:
            # 完整 HTML：直接在 </body> 前注入，不再外层包裹
            return echarts_html.replace("</body>", inject_html + "\n</body>")

        # 片段：仍用外壳包裹（保留历史行为）
        descriptions_js = "{\n"
        for node_name, desc in node_descriptions.items():
            escaped_desc = desc.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')
            descriptions_js += '    "{}": "{}",\n'.format(node_name, escaped_desc)
        descriptions_js += "}"

        html_template = """<!DOCTYPE html>
<html>
<head>
    <meta charset=\"utf-8\">
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">
    <title>动态桑基图-带项目描述</title>
    <style>
        * {{ box-sizing: border-box; }}
        body {{ margin: 0; padding: 0; font-family: Arial, sans-serif; background-color: #f5f5f5; height: 100vh; overflow: hidden; }}
        .container {{ background: white; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); padding: 10px; margin: 5px; height: calc(100vh - 10px); display: flex; flex-direction: column; }}
        .chart-container {{ flex: 1; min-height: 0; }}
        .modal {{ display: none; position: fixed; z-index: 1000; left: 0; top: 0; width: 100%; height: 100%; background-color: rgba(0,0,0,0.5); }}
        .modal-content {{ background-color: #fefefe; margin: 5% auto; padding: 20px; border-radius: 8px; width: 80%; max-width: 600px; box-shadow: 0 4px 20px rgba(0,0,0,0.3); position: relative; }}
        .close {{ color: #aaa; float: right; font-size: 28px; font-weight: bold; cursor: pointer; position: absolute; right: 15px; top: 10px; }}
        .close:hover, .close:focus {{ color: #000; text-decoration: none; }}
        .modal-title {{ font-size: 18px; font-weight: bold; margin-bottom: 15px; color: #333; border-bottom: 2px solid #4CAF50; padding-bottom: 10px; }}
        .modal-description {{ font-size: 14px; line-height: 1.6; color: #666; white-space: pre-line; }}
        .no-description {{ color: #999; font-style: italic; }}
    </style>
</head>
<body>
    <div class=\"container\">
        <div class=\"chart-container\">
            {ECHARTS_HTML}
        </div>
    </div>
    <div id=\"descriptionModal\" class=\"modal\">
        <div class=\"modal-content\">
            <span class=\"close\">&times;</span>
            <div class=\"modal-title\" id=\"modalTitle\">项目描述</div>
            <div class=\"modal-description\" id=\"modalDescription\"></div>
        </div>
    </div>

    <script>
        const nodeDescriptions = {DESCRIPTIONS_JS};
        const modal = document.getElementById('descriptionModal');
        const modalTitle = document.getElementById('modalTitle');
        const modalDescription = document.getElementById('modalDescription');
        const closeBtn = document.getElementsByClassName('close')[0];

        function showProjectDescription(nodeName) {{
            const description = nodeDescriptions[nodeName];
            modalTitle.textContent = nodeName || '未知节点';
            if (description) {{
                modalDescription.textContent = description;
                modalDescription.className = 'modal-description';
            }} else {{
                modalDescription.textContent = '暂无节点描述信息';
                modalDescription.className = 'modal-description no-description';
            }}
            modal.style.display = 'block';
        }}

        function closeModal() {{ modal.style.display = 'none'; }}
        closeBtn.onclick = closeModal;
        window.onclick = function(event) {{ if (event.target === modal) {{ closeModal(); }} }}
        document.addEventListener('keydown', function(event) {{ if (event.key === 'Escape') {{ closeModal(); }} }});

        document.addEventListener('DOMContentLoaded', function() {{
            setTimeout(function() {{
                const chartContainers = document.querySelectorAll('[id^="chart_"], .chart-container');
                let chart = null;
                for (let container of chartContainers) {{
                    chart = echarts.getInstanceByDom(container);
                    if (chart) {{ break; }}
                }}
                if (chart) {{
                    chart.on('click', function(params) {{
                        if (params.componentType === 'series' && params.dataType === 'node') {{
                            showProjectDescription(params.data.name);
                        }}
                    }});
                }}
            }, 2000);
        }});
    </script>
</body>
</html>"""

        # 使用占位符替换，避免与 CSS/JS 花括号冲突
        return (
            html_template
            .replace("{ECHARTS_HTML}", echarts_html)
            .replace("{DESCRIPTIONS_JS}", descriptions_js)
        )

    def create_node_with_style(self, node_name, node_descriptions=None, project_colors=None):
        import re
        node = {"name": node_name}
        pattern = r'^资源池[一二三四五六七八九十①②③④⑤⑥⑦⑧⑨⑩\d]+$'
        if bool(re.match(pattern, str(node_name))):
            node["itemStyle"] = {"color": "#B0B0B0"}
        elif project_colors:
            # 处理带金额的节点名称：项目名（会议：时间） 金额：xxx
            # 提取项目名称（去掉金额部分）
            if ' 金额：' in node_name:
                project_name = node_name.split(' 金额：')[0].split('（')[0]
            else:
                project_name = node_name.split('（')[0] if '（' in node_name else node_name
            if project_name in project_colors:
                node["itemStyle"] = {"color": project_colors[project_name]}
        if node_descriptions and node_name in node_descriptions:
            node["description"] = node_descriptions[node_name]
        return node

    def get_chart_title(self, budget_path):
        if budget_path and os.path.exists(budget_path):
            base_name = os.path.splitext(os.path.basename(budget_path))[0]
            return f"{base_name}-桑基图"
        else:
            return "桑基图"

    def _format_phase_totals_subtitle(self, phase_totals):
        """格式化会议总预算副标题：别名：会议名称 合计：xxx"""
        if not phase_totals:
            return ""
        subtitle_parts = []
        for alias, phase_name, total in phase_totals:
            # 格式化金额：如果是整数显示整数，否则显示2位小数
            if total == int(total):
                total_str = f"{int(total):,}"
            else:
                total_str = f"{total:,.2f}"
            subtitle_parts.append(f"{alias}：{phase_name} 合计：{total_str}")
        return " | ".join(subtitle_parts)

    def _calculate_subtitle_font_size(self, phase_totals):
        """根据副标题内容长度计算字体大小，确保美观"""
        if not phase_totals:
            return 12
        subtitle_text = self._format_phase_totals_subtitle(phase_totals)
        text_length = len(subtitle_text)
        # 根据长度自适应字体大小
        if text_length <= 50:
            return 14
        elif text_length <= 100:
            return 12
        elif text_length <= 150:
            return 10
        else:
            return 9

    def send_feishu_notification(self, html_file_path, budget_file_name):
        # 留空：由上层服务决定是否通知
        pass

    def generate_sankey_chart(self, edges_path, output_html_path, budget_path=None):
        try:
            edges_df = pd.read_excel(edges_path)
            value_col = None
            possible_value_cols = ['value', 'Value', 'VALUE', '数值', '金额', '数量', '流量']
            for col in possible_value_cols:
                if col in edges_df.columns:
                    value_col = col
                    break
            if value_col is None:
                self.logger.error("Excel文件中未找到数值列")
                return False
            valid_df = edges_df[(edges_df[value_col].notnull()) & (edges_df[value_col] > 0)]
            if len(valid_df) == 0:
                self.logger.warning("没有有效数据")
                return False
            node_descriptions = {}
            node_amounts = {}
            phase_totals = []  # 会议总预算列表
            if budget_path and os.path.exists(budget_path):
                node_descriptions = self.load_project_descriptions(budget_path)
                node_amounts = self.load_node_amounts(budget_path)
                phase_totals = self.compute_phase_totals(budget_path)  # 加载会议总预算
            
            # 创建节点名称到带金额的节点名称的映射
            node_name_mapping = {}
            # 创建显示名称映射（去掉时间，加上数字符号）
            display_name_mapping = {}
            nodes_set = set(valid_df['source']).union(set(valid_df['target']))
            for node_name in nodes_set:
                if node_name in node_amounts:
                    amount = node_amounts[node_name]
                    # 格式化金额：如果是整数显示整数，否则显示2位小数
                    if amount == int(amount):
                        amount_str = f"{int(amount):,}"
                    else:
                        amount_str = f"{amount:,.2f}"
                    new_node_name = f"{node_name} 金额：{amount_str}"
                    node_name_mapping[node_name] = new_node_name
                    
                    # 生成显示名称：去掉时间，加上数字符号
                    if '（' in node_name and '）' in node_name:
                        project = node_name.split('（')[0]
                        # 提取阶段别名（如"第一次"、"第二次"）
                        meeting_part = node_name.split('（')[1].split('）')[0]
                        if '：' in meeting_part:
                            phase_alias = meeting_part.split('：')[0]  # 提取"第一次"
                        else:
                            phase_alias = meeting_part
                        # 阶段别名到数字符号的映射（从①开始）
                        phase_symbol_map = {
                            "初始": "①",
                            "第一次": "②",
                            "第二次": "③",
                            "第三次": "④",
                            "第四次": "⑤",
                            "第五次": "⑥"
                        }
                        symbol = phase_symbol_map.get(phase_alias, "①")  # 默认用①
                        # 显示名称格式：符号项目名：金额数字（去掉"金额："文字）
                        display_name = f"{symbol}{project}：{amount_str}"
                    else:
                        display_name = new_node_name
                    display_name_mapping[new_node_name] = display_name
                else:
                    # 如果没有找到金额，保持原名称（资源池等节点）
                    node_name_mapping[node_name] = node_name
                    display_name_mapping[node_name] = node_name
            
            # 更新 edges 中的节点名称
            valid_df = valid_df.copy()
            valid_df['source'] = valid_df['source'].map(node_name_mapping)
            valid_df['target'] = valid_df['target'].map(node_name_mapping)
            
            # 更新节点集合
            nodes_set = set(valid_df['source']).union(set(valid_df['target']))
            projects = self.extract_projects_from_nodes(list(nodes_set))
            project_colors = {p: COLOR_PALETTE[i % len(COLOR_PALETTE)] for i, p in enumerate(projects)}
            
            # 更新节点描述映射（使用新的节点名称）
            updated_node_descriptions = {}
            for old_name, new_name in node_name_mapping.items():
                if old_name in node_descriptions:
                    updated_node_descriptions[new_name] = node_descriptions[old_name]
            
            # 创建节点时使用显示名称
            nodes = []
            for data_name in sorted(nodes_set):
                display_name = display_name_mapping.get(data_name, data_name)
                node_dict = self.create_node_with_style(data_name, updated_node_descriptions, project_colors)
                # 修改节点名称为显示名称
                node_dict['name'] = display_name
                # 如果完整名称有描述，保留描述
                if data_name in updated_node_descriptions:
                    node_dict['description'] = updated_node_descriptions[data_name]
                nodes.append(node_dict)
            
            # 更新links中的节点名称，使用显示名称
            links = []
            for _, row in valid_df.iterrows():
                if row['source'] != row['target']:  # 过滤原始数据的自循环
                    source_display = display_name_mapping.get(row['source'], row['source'])
                    target_display = display_name_mapping.get(row['target'], row['target'])
                    # 额外过滤：如果显示名称相同，也会形成自循环，需要过滤掉
                    if source_display != target_display:
                        links.append({
                            "source": source_display,
                            "target": target_display,
                            "value": float(row[value_col])
                        })
            
            # 创建显示名称到描述的映射（用于HTML弹窗）
            # 映射链：原始节点名称 -> 完整节点名称 -> 显示名称
            display_name_to_description = {}
            for original_name, description in node_descriptions.items():
                # 原始节点名称 -> 完整节点名称（通过node_name_mapping）
                full_name = node_name_mapping.get(original_name)
                if full_name:
                    # 完整节点名称 -> 显示名称（通过display_name_mapping）
                    display_name = display_name_mapping.get(full_name)
                    if display_name:
                        display_name_to_description[display_name] = description

            c = (
                Sankey(init_opts=opts.InitOpts(width="100%", height="100vh", page_title="动态桑基图"))
                .add(
                    "预算流向分析",
                    nodes=nodes,
                    links=links,
                    orient="horizontal",
                    node_align="justify",
                    node_gap=15,
                    node_width=15,
                    pos_top="8%",  # 为标题和副标题留出空间
                    linestyle_opt=opts.LineStyleOpts(opacity=0.6, curve=0.5, color="source"),
                    label_opts=opts.LabelOpts(position="right", formatter="{b}", font_size=9),
                    itemstyle_opts=opts.ItemStyleOpts(border_width=1, border_color="#ccc", opacity=0.9)
                )
                .set_global_opts(
                    title_opts=opts.TitleOpts(
                        title=self.get_chart_title(budget_path), 
                        pos_left="center", 
                        title_textstyle_opts=opts.TextStyleOpts(font_size=18),
                        subtitle=self._format_phase_totals_subtitle(phase_totals) if phase_totals else "",
                        subtitle_textstyle_opts=opts.TextStyleOpts(
                            font_size=self._calculate_subtitle_font_size(phase_totals)
                        )
                    ),
                    tooltip_opts=opts.TooltipOpts(trigger="item", trigger_on="mousemove", formatter="{b}"),
                    legend_opts=opts.LegendOpts(is_show=False)
                )
            )
            # 统一生成"完整 HTML 页面"，避免片段/完整混用导致的嵌套问题
            c.render(output_html_path)
            # 如存在节点描述，则在完整 HTML 中注入弹窗 DOM 与脚本
            if display_name_to_description:
                try:
                    with open(output_html_path, 'r', encoding='utf-8') as f:
                        generated_html = f.read()
                    full_html = self.create_html_with_popup(generated_html, display_name_to_description)
                    with open(output_html_path, 'w', encoding='utf-8') as f:
                        f.write(full_html)
                except Exception as inject_err:
                    self.logger.error("在完整HTML中注入弹窗失败: {}".format(inject_err))
                    return False
            self.logger.info("桑基图已生成: {}".format(output_html_path))
            return True
        except Exception as e:
            self.logger.error("生成桑基图时出错: {}".format(e))
            return False


