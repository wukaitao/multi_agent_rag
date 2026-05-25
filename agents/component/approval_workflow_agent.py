import sqlite3
import time
import json
import re
from datetime import datetime
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from enum import Enum
from core.memory_manager import save_long_memory
from core.security import data_desensitize
from config import MEMORY_DB
from database.neo4j_conn import _neo4j_conn

# ========== 枚举定义 ==========
class ApprovalStatus(Enum):
    """审批状态"""
    PENDING = "待审批"      # 等待审批
    APPROVED = "已通过"     # 审批通过
    REJECTED = "已驳回"     # 审批驳回
    CANCELLED = "已取消"    # 已取消
    TRANSFERRED = "已转交"  # 已转交
    EXPIRED = "已过期"      # 已过期

class ApprovalLevel(Enum):
    """审批级别"""
    LEVEL_1 = 1 # 一级审批 (部门主管)
    LEVEL_2 = 2 # 二级审批 (总监)
    LEVEL_3 = 3 # 三级审批 (VP)
    LEVEL_4 = 4 # 四级审批 (CEO/终审)

class ApprovalAction(Enum):
    """审批动作"""
    APPROVE = "approve"   # 通过
    REJECT = "reject"     # 驳回
    TRANSFER = "transfer" # 转交
    REMIND = "remind"     # 催办

# ========== 数据模型 ==========
@dataclass
class ApprovalConfig:
    """审批配置"""
    flow_id: str                # 流程ID
    flow_name: str              # 流程名称
    levels: List[Dict]          # 审批级别配置
    auto_approve: bool = False  # 是否自动通过
    timeout_days: int = 7       # 超时天数

@dataclass
class ApprovalRequest:
    """审批请求"""
    request_id: str             # 请求ID
    user: str                   # 申请人
    content: str                # 申请内容
    flow_type: str              # 流程类型
    current_level: int = 1      # 当前审批级别
    status: str = "待审批"       # 状态
    approver: str = ""          # 当前审批人
    created_at: str = ""        # 创建时间
    updated_at: str = ""        # 更新时间
    remark: str = ""            # 备注
    biz_data: Dict = None       # 业务数据

# ========== 数据表初始化(完善版) ==========
def init_apprval_tables():
    """初始化审批相关所有表"""
    conn = sqlite3.connect(MEMORY_DB)
    c = conn.cursor()

    # 1. 审批主表
    c.execute("""
        CREATE TABLE IF NOT EXISTS approval_main (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id TEXT UNIQUE NOT NULL,
            user TEXT NOT NULL,
            content TEXT NOT NULL,
            flow_type TEXT,
            flow_name TEXT,
            current_level INTEGER DEFAULT 1,
            status TEXT DEFAULT '待审批',
            created_at TEXT,
            updated_at TEXT,
            remark TEXT,
            biz_data TEXT
        )
    """)

    # 2. 审批记录表(每个级别的审批记录)
    c.execute("""
        CREATE TABLE IF NOT EXISTS approval_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id TEXT NOT NULL,
            level INTEGER NOT NULL,
            approver TEXT NOT NULL,
            action TEXT NOT NULL,
            comment TEXT,
            action_time TEXT,
            duration_days REAL,
            FOREIGN KEY (request_id) REFERENCES approval_main(request_id)
        )
    """)

    # 3. 审批人配置表
    c.execute("""
        CREATE TABLE IF NOT EXISTS approval_approvers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            flow_type TEXT NOT NULL,
            level INTEGER NOT NULL,
            approver_role TEXT NOT NULL,
            approver_name TEXT,
            approver_email TEXT,
            is_active INTEGER DEFAULT 1
        )
    """)

    # 4. 流程配置表
    c.execute("""
        CREATE TABLE IF NOT EXISTS approval_flows (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id TEXT UNIQUE NOT NULL,
            flow_type TEXT NOT NULL,
            flow_name TEXT NOT NULL,
            level_config TEXT,
            is_active INTEGER DEFAULT 1,
            created_at TEXT,
            updated_at TEXT
        )
    """)

    # 5. 通知记录表
    c.execute("""
        CREATE TABLE IF NOT EXISTS approval_notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id TEXT NOT NULL,
            recipient TEXT NOT NULL,
            type TEXT,
            content TEXT,
            is_read INTEGER DEFAULT 1,
            sent_at TEXT
        )
    """)

    conn.commit()
    conn.close()

    # 初始化默认审批人配置
    init_default_approvers()

def init_default_approvers():
    """初始化默认审批人配置"""
    conn = sqlite3.connect(MEMORY_DB)
    c = conn.cursor()
    print(f"==================================================================")

    # 检查是否已有配置
    c.execute("SELECT COUNT(*) FROM approval_approvers")
    if c.fetchone()[0] == 0:
        print(f"===88888888888888888888888888====")
        # 默认配置: 三级审批
        default_approvers = [
            # 通用审批流程
            ("general", 1, "部门主管", "张主管", "zhang@company.com"),
            ("general", 2, "总监", "李总监", "li@company.com"),
            ("general", 3, "CEO", "王总", "wang@company.com"),
            # 请假审批流程
            ("leave", 1, "部门主管", "张主管", "zhang@company.com"),
            ("leave", 2, "HR总监", "李总监", "li@company.com"),
            ("leave", 3, "CEO", "王总", "wang@company.com"),
            # 报销审批流程
            ("expense", 1, "部门主管", "张主管", "zhang@company.com"),
            ("expense", 2, "财务总监", "赵总监", "zhao@company.com"),
            # 项目审批流程
            ("project", 1, "项目经理", "孙经理", "sun@company.com"),
            ("project", 2, "技术总监", "周总监", "zhou@company.com"),
            ("project", 3, "VP", "吴总", "wu@company.com"),
            ("project", 4, "CEO", "王总", "wang@company.com")
        ]

        for flow_type, level, role, name, email in default_approvers:
            c.execute("""
                INSERT INTO approval_approvers (flow_type, level, approver_role, approver_name, approver_email)
                VALUES (?, ?, ?, ?, ?)
            """, (flow_type, level, role, name, email)
            )
        
        conn.commit()
        conn.close()

# 初始化所有表
# init_apprval_tables()

def log_to_sqlite(request_id: str, user: str, content: str, flow_type: str="normal", flow_name: str="普通审批", status: str = "待审批") -> int:
    """记录审批日志到 Sqlite"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(MEMORY_DB)
    c = conn.cursor()
    c.execute("""
        INSERT INTO approval_main
        (request_id, user, content, flow_type, flow_name, current_level, status, created_at, updated_at, biz_data)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, 
        (request_id, user, content, flow_type, flow_name, 1, status, now, now, "")
    )
    conn.commit()
    last_id = c.lastrowid
    conn.close()
    return last_id

def update_log_to_sqlite(request_id: str, status: str = ""):
    """更新 Human-in-Loop 审批状态"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(MEMORY_DB)
    c = conn.cursor()
    c.execute("""
        UPDATE approval_main
        SET status = ?, updated_at = ?
        WHERE request_id = ?
        """, (status, now, request_id)
    )
    conn.commit()
    conn.close()

# ========== 审批引擎核心类 ==========
class ApprovalEngine:
    """审批流程引擎"""

    def __init__(self):
        self.conn = sqlite3.connect(MEMORY_DB)
        self.conn.row_factory = sqlite3.Row

    def close(self):
        self.conn.close()

    def generate_request_id(self) -> str:
        """生成唯一请求ID"""
        return f"REQ{datetime.now().strftime('%Y%m%d%H%M%S')}{int (time.time() * 1000) % 1000:03d}"
    
    def submit_request(self, user: str, content: str, flow_type: str, biz_data: Dict = None) -> Dict:
        """
        提交审批流程
        Args:
            user: 申请人
            content: 申请内容
            flow_type: 业务类型(leave/expense/project等)
            biz_data: 业务数据
        """

        # 获取流程配置
        flow_config = self.get_flow_config(flow_type)
        if not flow_config:
            return {"success": False, "message": f"流程类型 '{flow_type}' 未配置"}
        
        # 获取第一级审批人
        first_approver = self.get_approver_by_level(flow_type, 1)
        print(f"flow_type: {flow_type}")
        print(f"first_approver:\n{first_approver}")

        request_id = self.generate_request_id()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        c = self.conn.cursor()
        c.execute("""
            INSERT INTO approval_main
            (request_id, user, content, flow_type, flow_name, current_level, status, created_at, updated_at, biz_data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, 
            (request_id, user, content, flow_type, flow_config.get("flow_name"), 1, "待审批", now, now, json.dumps(biz_data or {}))
        )

        # 创建一级审批记录
        c.execute("""
            INSERT INTO approval_records (request_id, level, approver, action, action_time)
            VALUES (?, ?, ?, ?, ?)
            """, (request_id, 1, first_approver.get("approver_name", ""), "pending", now)
        )

        self.conn.commit()

        # 发送通知
        self.send_notification(request_id, first_approver.get("approver_email"), "待审批", content)

        return {
            "success": True,
            "request_id": request_id,
            "message": f"申请已提交, 当前等待 {first_approver.get("approver_name")} 审批",
            "current_approver": first_approver.get("approver_name")
        }
    
    def approve(self, request_id: str, approver: str, comment: str = "") -> Dict:
        """
        审批通过
        Args:
            request_id: 申请ID
            approver: 审批人
            comment: 审批意见
        """

        # 获取申请信息
        request = self.get_request(request_id)
        if not request:
            return {
                "success": False,
                "message": "申请不存在"
            }
        if request["status"] != "待审批":
            return {
                "success": False,
                "message": f"当前状态为 {request['status']}, 无法审批"
            }
        
        current_level = request["current_level"]
        flow_type = request["flow_type"]

        # 检查当前审批人是否有权限
        expected_approver = self.get_approver_by_level(flow_type, current_level)
        if expected_approver.get("approver_name") != approver:
            return {
                "success": False,
                "message": f"当前审批人应为 {expected_approver.get("approver_name")}"
            }
        
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 更新当前级别的审批记录
        c = self.conn.cursor()
        start_time = self.get_approval_start_time(request_id, current_level)
        duration = self.calculate_duration(start_time, now) if start_time else 0

        c.execute("""
            UPDATE approval_records
            SET action = ?, comment = ?, action_time = ?, duration_days = ?
            WHERE request_id = ? AND level = ?
            """, ("approve", comment, now, duration, request_id, current_level)
        )

        # 检查是否有下一级
        next_level = current_level + 1
        next_approver = self.get_approver_by_level(flow_type, next_level)

        if next_approver and next_level <= 5: # 最多5级审批
            # 流转到下一级
            c.execute("""
                UPDATE approval_main
                SET current_level = ?, updated_at = ?
                WHERE request_id = ?
                """, (next_level, now, request_id)
            )

            # 创建下一级审批记录
            c.execute("""
                INSERT INTO approval_records (request_id, level, approver, action, action_time)
                VALUES (?, ?, ?, ?, ?)
                """, (request_id, next_level, next_approver.get("approver_name"), "pending", now)
            )
            
            self.conn.commit()

            # 发送通知给下一级审批人
            self.send_notification(request_id, next_approver.get("approver_name"), "待审批", request["content"])

            return {
                "success": True,
                "message": f"审批通过, 已流转至 {next_approver.get("approver_name")} 审批",
                "next_level": next_level,
                "next_approver": next_approver.get("approver_name")
            }
        else:
            # 审批完成
            c.execute("""
                UPDATE approval_main
                SET status = ?, updated_at = ?
                WHERE request_id = ?
                """, ("已通过", now, request_id)
            )

            self.conn.commit()

            # 通知申请人
            self.send_notification(request_id, request["user"], "已完成", request["content"])

            # 执行业务回调
            self.execute_business_callback(request)

            return {
                "success": True,
                "message": "审批流程已完成",
                "final_status": "approved"
            }
        
    def reject(self, request_id: str, approver: str, comment: str = "") -> Dict:
        """
        审批驳回
        Args:
            request_id: 申请ID
            approver: 审批人
            comment: 驳回原因
        """

        # 获取申请信息
        request = self.get_request(request_id)
        if not request:
            return {
                "success": False,
                "message": "申请不存在"
            }
        if request["status"] != "待审批":
            return {
                "success": False,
                "message": f"当前状态为 {request['status']}, 无法审批"
            }
        
        current_level = request["current_level"]
        flow_type = request["flow_type"]

        # 检查当前审批人是否有权限
        expected_approver = self.get_approver_by_level(flow_type, current_level)
        if expected_approver.get("approver_name") != approver:
            return {
                "success": False,
                "message": f"当前审批人应为 {expected_approver.get("approver_name")}"
            }
        
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        c = self.conn.cursor()

        # 更新当前界别审批记录
        c.execute("""
            UPDATE approval_records
            SET action = ?, comment = ?, action_time = ?
            WHERE request_id = ? AND level = ?
            """, ("reject", comment, now, request_id, request["current_level"])
        )

        # 更新主表状态
        c.execute("""
            UPDATE approval_main
            SET status = ?, updated_at = ?, remark = ?
            WHERE request_id = ?
            """, ("已驳回", now, comment, request_id)
        )

        self.conn.commit()

        # 通知申请人
        self.send_notification(request_id, request["user"], "已驳回", f"驳回意见: {comment}")

        return {
            "success": True,
            "message": "申请已被驳回",
            "reason": comment
        }
    
    def transfer(self, request_id: str, from_approver: str, to_approver: str, reason: str = "") -> Dict:
        """
        转交审批
        Args:
            request_id: 申请ID
            from_approver: 转移人
            to_approver: 接收人
            reason: 转交原因
        """

        # 获取申请信息
        request = self.get_request(request_id)
        if not request:
            return {
                "success": False,
                "message": "申请不存在"
            }
        if request["status"] != "待审批":
            return {
                "success": False,
                "message": f"当前状态为 {request['status']}, 无法审批"
            }
        
        current_level = request["current_level"]
        flow_type = request["flow_type"]

        # 检查当前审批人是否有权限
        expected_approver = self.get_approver_by_level(flow_type, current_level)
        if expected_approver.get("approver_name") != from_approver:
            return {
                "success": False,
                "message": f"当前审批人应为 {expected_approver.get("approver_name")}"
            }
        
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        c = self.conn.cursor()

        # 记录转交
        c.execute("""
            INSERT INTO approval_records (request_id, level, approver, action, comment, action_time)
            VALUES (?, ?, ?, ?, ?, ?)
            """, (request_id, current_level, from_approver, "transfer", f"转交给 {to_approver}, 原因: {reason}", now)
        )

        # 创建新的审批记录
        c.execute("""
            INSERT INTO approval_records (request_id, level, approver, action, action_time)
            VALUES (?, ?, ?, ?, ?)
            """, (request_id, current_level, to_approver, "pending", now)
        )

        self.conn.commit()

        return {
            "success": True,
            "message": f"已转交给 {to_approver} 处理"
        }
    
    def get_request(self, request_id: str) -> Optional[Dict]:
        """获取申请详情"""
        c = self.conn.cursor()
        c.execute("SELECT * FROM approval_main WHERE request_id = ?", (request_id,))
        row = c.fetchone()
        if row:
            result = dict(row)
            result["biz_data"] = json.loads(result["biz_data"]) if result["biz_data"] else {}
            return result
        return None
    
    def get_approval_history(self, request_id: str) -> List[Dict]:
        """获取审批历史"""
        c = self.conn.cursor()
        c.execute("""
            SELECT * FROM approval_records
            WHERE request_id = ?
            ORDER BY level, id
            """, (request_id,)
        )
        return [dict(row) for row in c.fetchall()]

    def get_flow_config(self, flow_type: str) -> Optional[Dict]:
        """获取流程配置"""
        c = self.conn.cursor()
        c.execute("SELECT * FROM approval_flows WHERE flow_type = ? AND is_active = 1", (flow_type,))
        row = c.fetchone()
        if row:
            result = dict(row)
            result["levels_config"] = json.loads(result["levels_config"]) if result["levels_config"] else []
            return result
        
        # 如果没有配置, 返回默认配置
        return self.get_default_flow_config(flow_type)
    
    def get_default_flow_config(self, flow_type: str) -> Dict:
        """获取默认流程配置"""
        configs = {
            "leave": {"flow_name": "请假审批", "levels": [1, 2, 3]},
            "expense": {"flow_name": "报销审批", "levels": [1, 2]},
            "project": {"flow_name": "项目立项", "levels": [1, 2, 3, 4]}
        }
        default = configs.get(flow_type, {"flow_name": "通用审批", "levels": [1, 2]})
        return {
            "flow_type": flow_type,
            "flow_name": default["flow_name"],
            "is_active": 1
        }
    
    def get_approver_by_level(self, flow_type: str, level: int) -> Optional[Dict]:
        """获取指定级别的审批人"""
        c = self.conn.cursor()
        c.execute("""
            SELECT * FROM approval_approvers 
            WHERE flow_type = ? AND level = ? AND is_active = 1
            """, (flow_type, level)
        )
        row = c.fetchone()
        return dict(row) if row else None
    
    def get_pending_requests(self, approver: str) -> List[Dict]:
        """获取待审批列表"""
        c = self.conn.cursor()
        c.execute("""
            SELECT a.*, r.approver, r.level as current_approval_level 
            FROM approval_main a
            JOIN approval_records r ON a.request_id = r.request_id
            WHERE r.approver = ? AND r.action = 'pending' AND a.status = "待审批"
            ORDER BY a.created_at DESC
            """, (approver,)
        )
        return [dict(row) for row in c.fetchall()]
    
    def get_my_requests(self, user: str) -> List[Dict]:
        """获取我的审批列表"""
        c = self.conn.cursor()
        c.execute("""
            SELECT * FROM approval_main
            WHERE user = ? ORDER BY created_at DESC
            """, (user,)
        )
        return [dict(row) for row in c.fetchall()]
    
    def send_notification(self, request_id: str, recipient: str, action: str, content: str):
        """发送通知"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        c = self.conn.cursor()
        c.execute("""
            INSERT INTO approval_notifications (request_id, recipient, type, content, sent_at)
            VALUES (?, ?, ?, ?, ?)
            """, (request_id, recipient, action, content, now)
        )
        self.conn.commit()

    def get_notifycations(self, recipient: str, unread_only: bool = True) -> List[Dict]:
        """获取通知列表"""
        c = self.conn.cursor()
        query = """
            SELECT * FROM approval_notifications
            WHERE recipient = ?
        """
        params = [recipient]
        if unread_only:
            query += " AND is_read = 0"
        query += " ORDER BY sent_at DESC"

        c.execute(query, params)
        return [dict(row) for row in c.fetchall()]
    
    def mark_notification_read(self, notification_id: int):
        """标记通知已读"""
        c = self.conn.cursor()
        c.execute("""
            UPDATE approval_notifications SET is_read = 1 WHERE id = ?
            """, (notification_id)
        )
        self.conn.commit()

    def get_approval_start_time(self, request_id: str, level: int) -> Optional[str]:
        """获取某级审批开始时间"""
        c = self.conn.cursor()
        c.execute("""
            SELECT action_time FROM approval_records
            WHERE request_id = ? AND level = ? AND action = 'pending'
            """, (request_id, level)
        )
        row = c.fetchone()
        return row["action_time"] if row else None
    
    def calculate_duration(self, start_time: str, end_time: str) -> float:
        """计算耗时(天数)"""
        start = datetime.strptime(start_time, "%Y-%m-%d %H:%M:%S")
        end = datetime.strptime(end_time, "%Y-%m-%d %H:%M:%S")
        return round((end - start).total_seconds() / 3600/ 24, 2)
    
    def execute_business_callback(self, request: Dict):
        """执行审批通过后的业务回调"""
        flow_type = request["flow_type"]
        biz_data = request["biz_data"]

        if flow_type == "leave":
            # 请假通过: 更新考勤系统
            print(f"请假申请已批准: {biz_data}")
        elif flow_type == "expense":
            # 报销通过: 触发财务流程
            print(f"报销申请已批准: {biz_data}")
        elif flow_type == "project":
            # 项目立项通过: 触发立项流程
            print(f"项目立项已批准: {biz_data}")
        elif flow_type == "delete_kg":
            # 删除知识图谱
            try: 
                _neo4j_conn.kg_clear_all()
                print(f"知识图谱已删除")
            except Exception as e:
                print(f"知识图谱删除失败:  {str(e)}")
        else:
            print(f"未定义的审批回调业务")

def get_approval_engine():
    """引擎实例化"""
    return ApprovalEngine()

def handle_workflow_submit(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    普通审批流程(企业级)
    支持多级审批/审批人配置/通知等
    """
    user = state["user"]
    query = state["query"]
    content = data_desensitize(query)

    # 识别审批类型
    flow_type = "normal"
    if "请假" in query:
        flow_type = "leave"
    elif "报销" in query:
        flow_type = "expense"
    elif "项目" in query or "立项" in query:
        flow_type = "project"
    elif "删除知识图谱" in query:
        flow_type = "delete_kg"

    # 提交申请到审批引擎
    engine = get_approval_engine()
    result = engine.submit_request(
        user=user,
        content=content,
        flow_type=flow_type,
        biz_data={"query": query, "source": "智能问答"}
    )
    print("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")

    if result["success"]:
        res = f"""
            **{flow_type}审批流程启动**
            - **申请单号**: {result['request_id']}
            - **申请人**: {user}
            - **申请内容**: {content}
            - **申请状态**: 待审批
            - **当前审批人**: {result["current_approver"]}

            **流程链路**:
            {'->'.join(f"第{i}级审批" for i in range(1, 5) if engine.get_approver_by_level(flow_type, i))}
            审批人可在 [审批后台] 查看和处理申请
        """
    else:
        res = f"提交失败: {result["message"]}"
    
    state["response"] = res
    state["route"] = "end"
    return state

def handle_workflow_approval(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    处理审批动作(通过/驳回/转交)
    由审批后台调用
    """
    query = state["query"]
    user = state["user"]
    # 解析审批指令
    # 格式示例：通过 REQ202412011200001、驳回 REQ202412011200001 理由不充分
    match = re.match(r'(通过|驳回|转交)\s+([A-Z0-9]+)\s*(.*)', query)
    if not match:
        state["response"] = "指令格式错误, 请使用: 通过 申请单号 [意见]"
        state["route"] = "end"
        return state
    
    action, request_id, comment = match.groups()

    engine = get_approval_engine()

    if action == "通过":
        result = engine.approve(request_id, user, comment)
    elif action == "驳回":
        result = engine.reject(request_id, user, comment)
    elif action == "转交":
        # 转交给其他人: 转交 REQ123 张三
        target = comment.split()[0] if comment else ""
        result = engine.transfer(request_id, user, target, comment)
    else:
        result = {"success": False, "message": "未知操作"}

    state["response"] = result["message"]
    return state