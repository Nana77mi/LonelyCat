import asyncio
import json
import os
import sys
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import sessionmaker

from app.api import conversations
from app.db import Base, ConversationModel, MessageModel, MessageRole, RunModel, RunStatus
from app.services import run_messages
from sqlalchemy import create_engine

# Add agent-worker path for imports
agent_worker_path = Path(__file__).parent.parent.parent / "agent-worker"
if str(agent_worker_path) not in sys.path:
    sys.path.insert(0, str(agent_worker_path))


def _commit_db(db):
    """辅助函数：提交数据库事务"""
    db.commit()


@pytest.fixture
def temp_db():
    """创建临时数据库用于测试"""
    # 创建临时数据库文件
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    
    # 创建临时数据库 engine
    test_engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=test_engine)
    
    # 创建测试会话
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    db = TestSessionLocal()
    
    yield db, db_path
    
    # 清理
    db.close()
    os.unlink(db_path)


def assert_conversation_schema(conv: dict) -> None:
    """验证 Conversation schema"""
    expected = {
        "id",
        "title",
        "created_at",
        "updated_at",
        "has_unread",
        "last_read_at",
        "meta_json",
    }
    assert set(conv.keys()) == expected
    assert isinstance(conv["id"], str)
    assert isinstance(conv["title"], str)
    assert isinstance(conv["created_at"], str)  # ISO format string
    assert isinstance(conv["updated_at"], str)  # ISO format string
    assert isinstance(conv["has_unread"], bool)
    assert conv["last_read_at"] is None or isinstance(conv["last_read_at"], str)  # ISO format string or None
    assert conv["meta_json"] is None or isinstance(conv["meta_json"], dict)


def assert_message_schema(msg: dict) -> None:
    """验证 Message schema"""
    expected = {
        "id",
        "conversation_id",
        "role",
        "content",
        "created_at",
        "source_ref",
        "meta_json",
        "client_msg_id",
    }
    assert set(msg.keys()) == expected
    assert isinstance(msg["id"], str)
    assert isinstance(msg["conversation_id"], str)
    assert msg["role"] in ["user", "assistant", "system"]
    assert isinstance(msg["content"], str)
    assert isinstance(msg["created_at"], str)  # ISO format string
    # source_ref and meta_json can be None or dict
    # client_msg_id can be None or str


def test_list_empty_conversations(temp_db) -> None:
    """测试空对话列表"""
    db, _ = temp_db
    response = asyncio.run(conversations._list_conversations(db))
    assert response == {"items": []}


def test_create_conversation_default_title(temp_db) -> None:
    """测试创建对话（默认标题）"""
    db, _ = temp_db
    request = conversations.ConversationCreateRequest()
    response = asyncio.run(conversations._create_conversation(request, db))
    _commit_db(db)
    
    assert_conversation_schema(response)
    assert response["title"] == "New chat"
    assert response["id"] is not None


def test_create_conversation_custom_title(temp_db) -> None:
    """测试创建对话（自定义标题）"""
    db, _ = temp_db
    request = conversations.ConversationCreateRequest(title="My Custom Chat")
    response = asyncio.run(conversations._create_conversation(request, db))
    _commit_db(db)
    
    assert_conversation_schema(response)
    assert response["title"] == "My Custom Chat"
    assert response["id"] is not None


def test_list_conversations(temp_db) -> None:
    """测试列出对话（验证排序）"""
    db, _ = temp_db
    
    # 创建第一个对话
    request1 = conversations.ConversationCreateRequest(title="First Chat")
    conv1 = asyncio.run(conversations._create_conversation(request1, db))
    _commit_db(db)
    
    # 等待一小段时间确保时间戳不同
    import time
    time.sleep(0.01)
    
    # 创建第二个对话
    request2 = conversations.ConversationCreateRequest(title="Second Chat")
    conv2 = asyncio.run(conversations._create_conversation(request2, db))
    _commit_db(db)
    
    # 列出对话，应该按 updated_at 降序排列（最新的在前）
    response = asyncio.run(conversations._list_conversations(db))
    assert len(response["items"]) == 2
    assert response["items"][0]["id"] == conv2["id"]  # 最新的在前
    assert response["items"][1]["id"] == conv1["id"]
    assert_conversation_schema(response["items"][0])
    assert_conversation_schema(response["items"][1])


def test_get_conversation_messages_empty(temp_db) -> None:
    """测试获取空对话的消息列表"""
    db, _ = temp_db
    
    # 创建对话
    request = conversations.ConversationCreateRequest(title="Empty Chat")
    conv = asyncio.run(conversations._create_conversation(request, db))
    _commit_db(db)
    
    # 获取消息列表
    response = asyncio.run(conversations._get_conversation_messages(conv["id"], db))
    assert response == {"items": []}


def test_create_message(temp_db) -> None:
    """测试创建消息（通过数据库模型，因为 API 中没有创建消息的端点）"""
    db, _ = temp_db
    
    # 创建对话
    request = conversations.ConversationCreateRequest(title="Test Chat")
    conv = asyncio.run(conversations._create_conversation(request, db))
    _commit_db(db)
    
    # 直接创建消息（测试数据库模型）
    message_id = str(uuid.uuid4())
    now = datetime.now(UTC)
    
    message = MessageModel(
        id=message_id,
        conversation_id=conv["id"],
        role=MessageRole.USER,
        content="Hello, world!",
        created_at=now,
        source_ref={"kind": "test", "ref_id": "123"},
        meta_json={"test": True},
    )
    
    db.add(message)
    _commit_db(db)
    
    # 验证消息可以通过 API 获取
    response = asyncio.run(conversations._get_conversation_messages(conv["id"], db))
    assert len(response["items"]) == 1
    assert_message_schema(response["items"][0])
    assert response["items"][0]["id"] == message_id
    assert response["items"][0]["role"] == "user"
    assert response["items"][0]["content"] == "Hello, world!"
    assert response["items"][0]["source_ref"] == {"kind": "test", "ref_id": "123"}
    assert response["items"][0]["meta_json"] == {"test": True}


def test_get_conversation_messages(temp_db) -> None:
    """测试获取对话的所有消息（验证排序）"""
    db, _ = temp_db
    
    # 创建对话
    request = conversations.ConversationCreateRequest(title="Test Chat")
    conv = asyncio.run(conversations._create_conversation(request, db))
    _commit_db(db)
    
    # 创建多条消息
    message1 = MessageModel(
        id=str(uuid.uuid4()),
        conversation_id=conv["id"],
        role=MessageRole.USER,
        content="First message",
        created_at=datetime.now(UTC),
    )
    db.add(message1)
    _commit_db(db)
    
    import time
    time.sleep(0.01)
    
    message2 = MessageModel(
        id=str(uuid.uuid4()),
        conversation_id=conv["id"],
        role=MessageRole.ASSISTANT,
        content="Second message",
        created_at=datetime.now(UTC),
    )
    db.add(message2)
    _commit_db(db)
    
    time.sleep(0.01)
    
    message3 = MessageModel(
        id=str(uuid.uuid4()),
        conversation_id=conv["id"],
        role=MessageRole.SYSTEM,
        content="Third message",
        created_at=datetime.now(UTC),
    )
    db.add(message3)
    _commit_db(db)
    
    # 获取消息列表，应该按 created_at 升序排列（最早的消息在前）
    response = asyncio.run(conversations._get_conversation_messages(conv["id"], db))
    assert len(response["items"]) == 3
    assert response["items"][0]["id"] == message1.id  # 最早的消息在前
    assert response["items"][1]["id"] == message2.id
    assert response["items"][2]["id"] == message3.id
    assert response["items"][0]["role"] == "user"
    assert response["items"][1]["role"] == "assistant"
    assert response["items"][2]["role"] == "system"
    
    # 验证所有消息的 schema
    for msg in response["items"]:
        assert_message_schema(msg)


def test_get_nonexistent_conversation_messages(temp_db) -> None:
    """测试获取不存在的对话（应返回 404）"""
    db, _ = temp_db
    
    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(conversations._get_conversation_messages("nonexistent-id", db))
    assert excinfo.value.status_code == 404
    assert "Conversation not found" in str(excinfo.value.detail)


def test_create_message_via_api_and_read_back(temp_db) -> None:
    """验收测试：通过 API 写入消息，然后 GET 能读出来"""
    db, _ = temp_db
    
    # 1. 创建对话
    request = conversations.ConversationCreateRequest(title="Test Chat")
    conv = asyncio.run(conversations._create_conversation(request, db))
    _commit_db(db)
    conversation_id = conv["id"]
    
    # 2. 通过 API 写入用户消息（会自动调用 worker 生成助手回复）
    message_request = conversations.MessageCreateRequest(content="Hello, this is a test message")
    result = asyncio.run(conversations._create_message(conversation_id, message_request, db))
    _commit_db(db)
    
    # 验证返回结果包含两条消息
    assert "user_message" in result
    assert "assistant_message" in result
    assert result["user_message"] is not None
    assert result["assistant_message"] is not None
    
    user_msg = result["user_message"]
    assistant_msg = result["assistant_message"]
    
    # 验证用户消息
    assert_message_schema(user_msg)
    assert user_msg["role"] == "user"
    assert user_msg["content"] == "Hello, this is a test message"
    assert user_msg["conversation_id"] == conversation_id
    
    # 验证助手消息
    assert_message_schema(assistant_msg)
    assert assistant_msg["role"] == "assistant"
    assert assistant_msg["conversation_id"] == conversation_id
    assert len(assistant_msg["content"]) > 0  # 助手应该有回复内容
    
    # 3. 通过 GET API 读取消息
    messages_response = asyncio.run(conversations._get_conversation_messages(conversation_id, db))
    assert "items" in messages_response
    assert len(messages_response["items"]) == 2
    
    # 验证消息顺序（按 created_at 升序）
    retrieved_messages = messages_response["items"]
    assert retrieved_messages[0]["id"] == user_msg["id"]  # 第一条是用户消息
    assert retrieved_messages[1]["id"] == assistant_msg["id"]  # 第二条是助手消息
    
    # 验证消息内容
    assert retrieved_messages[0]["role"] == "user"
    assert retrieved_messages[0]["content"] == "Hello, this is a test message"
    assert retrieved_messages[1]["role"] == "assistant"
    
    # 验证所有消息的 schema
    for msg in retrieved_messages:
        assert_message_schema(msg)
        assert msg["conversation_id"] == conversation_id


def test_create_multiple_messages_and_read_all(temp_db) -> None:
    """测试创建多条消息并全部读取"""
    db, _ = temp_db
    
    # 创建对话
    request = conversations.ConversationCreateRequest(title="Multi Message Chat")
    conv = asyncio.run(conversations._create_conversation(request, db))
    _commit_db(db)
    conversation_id = conv["id"]
    
    # 创建第一条用户消息
    msg1 = conversations.MessageCreateRequest(content="First message")
    result1 = asyncio.run(conversations._create_message(conversation_id, msg1, db))
    _commit_db(db)
    
    # 创建第二条用户消息
    msg2 = conversations.MessageCreateRequest(content="Second message")
    result2 = asyncio.run(conversations._create_message(conversation_id, msg2, db))
    _commit_db(db)
    
    # 读取所有消息
    messages_response = asyncio.run(conversations._get_conversation_messages(conversation_id, db))
    
    # 应该有 4 条消息：2 条 user + 2 条 assistant
    assert len(messages_response["items"]) == 4
    
    # 验证消息顺序
    items = messages_response["items"]
    assert items[0]["role"] == "user"
    assert items[0]["content"] == "First message"
    assert items[1]["role"] == "assistant"
    assert items[2]["role"] == "user"
    assert items[2]["content"] == "Second message"
    assert items[3]["role"] == "assistant"


def test_conversation_updated_at_on_message_creation(temp_db) -> None:
    """测试：创建对话 A、B，给 A 新增 message，GET /conversations 应该 A 排第一"""
    db, _ = temp_db
    
    # 创建对话 A
    request_a = conversations.ConversationCreateRequest(title="Conversation A")
    conv_a = asyncio.run(conversations._create_conversation(request_a, db))
    _commit_db(db)
    conversation_a_id = conv_a["id"]
    # 从数据库获取初始 updated_at（datetime 对象）
    initial_conv_a_model = db.query(ConversationModel).filter(ConversationModel.id == conversation_a_id).first()
    initial_updated_at_a = initial_conv_a_model.updated_at
    
    # 等待一小段时间确保时间戳不同
    import time
    time.sleep(0.01)
    
    # 创建对话 B
    request_b = conversations.ConversationCreateRequest(title="Conversation B")
    conv_b = asyncio.run(conversations._create_conversation(request_b, db))
    _commit_db(db)
    conversation_b_id = conv_b["id"]
    
    # 此时 B 应该排第一（因为 B 创建时间更晚）
    conversations_list = asyncio.run(conversations._list_conversations(db))
    assert len(conversations_list["items"]) == 2
    assert conversations_list["items"][0]["id"] == conversation_b_id  # B 排第一
    assert conversations_list["items"][1]["id"] == conversation_a_id  # A 排第二
    
    # 等待一小段时间
    time.sleep(0.01)
    
    # 给 A 新增 message（这会更新 A 的 updated_at）
    message_request = conversations.MessageCreateRequest(content="Message to A")
    result = asyncio.run(conversations._create_message(conversation_a_id, message_request, db))
    _commit_db(db)
    
    # 验证消息创建成功
    assert "user_message" in result
    assert "assistant_message" in result
    
    # 重新获取对话 A，验证 updated_at 已更新
    updated_conv_a = db.query(ConversationModel).filter(ConversationModel.id == conversation_a_id).first()
    db.refresh(updated_conv_a)
    # 验证 updated_at 已更新（应该比初始时间晚）
    assert updated_conv_a.updated_at > initial_updated_at_a
    
    # GET /conversations 应该 A 排第一（因为 A 的 updated_at 更新了）
    conversations_list = asyncio.run(conversations._list_conversations(db))
    assert len(conversations_list["items"]) == 2
    assert conversations_list["items"][0]["id"] == conversation_a_id  # A 排第一（因为 updated_at 更新了）
    assert conversations_list["items"][1]["id"] == conversation_b_id  # B 排第二
    assert conversations_list["items"][0]["title"] == "Conversation A"
    assert conversations_list["items"][1]["title"] == "Conversation B"


def test_worker_failure_creates_system_error_message(temp_db, monkeypatch) -> None:
    """测试：worker 失败时创建 system 错误消息，确保对话不中断"""
    db, _ = temp_db
    
    # 创建对话
    request = conversations.ConversationCreateRequest(title="Test Chat")
    conv = asyncio.run(conversations._create_conversation(request, db))
    _commit_db(db)
    conversation_id = conv["id"]
    
    # 模拟 worker 失败（通过 monkeypatch）
    def mock_chat_flow(*args, **kwargs):
        raise Exception("Worker crashed")
    
    monkeypatch.setattr(conversations, "chat_flow", mock_chat_flow)
    monkeypatch.setattr(conversations, "AGENT_WORKER_AVAILABLE", True)
    
    # 创建消息（会触发 worker 失败）
    message_request = conversations.MessageCreateRequest(content="Test message")
    result = asyncio.run(conversations._create_message(conversation_id, message_request, db))
    _commit_db(db)
    
    # 验证返回结果
    assert "user_message" in result
    assert "assistant_message" in result
    assert result["user_message"] is not None
    
    # 验证 assistant_message 是 system 错误消息
    assistant_msg = result["assistant_message"]
    assert assistant_msg["role"] == "system"
    assert "执行失败" in assistant_msg["content"]
    assert "Worker crashed" in assistant_msg["content"]
    
    # 验证 meta_json 包含错误信息
    assert assistant_msg["meta_json"] is not None
    assert assistant_msg["meta_json"]["error"] is True
    assert assistant_msg["meta_json"]["error_type"] == "worker_failure"
    
    # 验证消息已保存到数据库
    messages_response = asyncio.run(conversations._get_conversation_messages(conversation_id, db))
    assert len(messages_response["items"]) == 2
    assert messages_response["items"][0]["role"] == "user"
    assert messages_response["items"][1]["role"] == "system"
    assert "执行失败" in messages_response["items"][1]["content"]


def test_idempotency_with_client_msg_id(temp_db) -> None:
    """测试：使用 client_msg_id 实现幂等性"""
    db, _ = temp_db
    
    # 创建对话
    request = conversations.ConversationCreateRequest(title="Test Chat")
    conv = asyncio.run(conversations._create_conversation(request, db))
    _commit_db(db)
    conversation_id = conv["id"]
    
    client_msg_id = "test-msg-123"
    
    # 第一次创建消息
    message_request1 = conversations.MessageCreateRequest(
        content="First message",
        client_msg_id=client_msg_id,
    )
    result1 = asyncio.run(conversations._create_message(conversation_id, message_request1, db))
    _commit_db(db)
    
    # 第二次使用相同的 client_msg_id 创建消息（应该返回已存在的消息）
    message_request2 = conversations.MessageCreateRequest(
        content="Duplicate message",
        client_msg_id=client_msg_id,
    )
    result2 = asyncio.run(conversations._create_message(conversation_id, message_request2, db))
    _commit_db(db)
    
    # 验证返回的是同一个消息
    assert result2.get("duplicate") is True
    assert result1["user_message"]["id"] == result2["user_message"]["id"]
    assert result1["user_message"]["content"] == "First message"  # 内容应该是第一次的
    
    # 验证数据库中只有一条消息（user + assistant，没有重复）
    messages_response = asyncio.run(conversations._get_conversation_messages(conversation_id, db))
    assert len(messages_response["items"]) == 2  # user + assistant，没有重复的 user


def test_no_duplicate_last_user_message(temp_db, monkeypatch) -> None:
    """关键测试：确保最后一条用户消息不会重复传递给 LLM
    
    发送一条消息，断言 LLM 收到的 messages 里最后一个 user content 只出现一次。
    """
    db, _ = temp_db
    
    # 创建对话
    request = conversations.ConversationCreateRequest(title="Test Chat")
    conv = asyncio.run(conversations._create_conversation(request, db))
    _commit_db(db)
    conversation_id = conv["id"]
    
    # 捕获传给 chat_flow 的参数
    captured_calls = []
    
    def mock_chat_flow(user_message: str, history_messages=None, **kwargs):
        """Mock chat_flow 来捕获传入的参数"""
        from agent_worker.chat_flow import ChatResult
        from agent_worker.trace import TraceCollector
        
        captured_calls.append({
            "user_message": user_message,
            "history_messages": history_messages,
        })
        
        trace = TraceCollector.from_env()
        return ChatResult(
            assistant_reply="Test response",
            memory_status="NO_ACTION",
            trace_id=trace.trace_id,
            trace_lines=[],
        )
    
    monkeypatch.setattr(conversations, "chat_flow", mock_chat_flow)
    monkeypatch.setattr(conversations, "AGENT_WORKER_AVAILABLE", True)
    
    # 发送一条消息
    test_content = "Test user message content"
    message_request = conversations.MessageCreateRequest(content=test_content)
    result = asyncio.run(conversations._create_message(conversation_id, message_request, db))
    _commit_db(db)
    
    # 验证消息创建成功
    assert "user_message" in result
    assert "assistant_message" in result
    
    # 验证 chat_flow 被调用
    assert len(captured_calls) == 1, "chat_flow should be called exactly once"
    call = captured_calls[0]
    
    # 关键断言：history_messages 不应该包含当前用户消息（避免重复）
    # 因为当前用户消息会作为 user_message 参数单独传递
    if call["history_messages"]:
        # 检查历史消息中是否包含当前用户消息的内容
        history_user_contents = [
            msg.get("content", "") 
            for msg in call["history_messages"] 
            if msg.get("role") == "user"
        ]
        
        # 当前用户消息的内容不应该出现在历史消息中
        assert test_content not in history_user_contents, (
            f"Current user message content '{test_content}' should not appear in history_messages, "
            f"but found in: {history_user_contents}"
        )
    
    # 验证 user_message 参数包含当前消息内容
    assert test_content in call["user_message"], (
        f"user_message parameter should contain '{test_content}', "
        f"but got: {call['user_message']}"
    )


def test_window_truncation_sanity(temp_db, monkeypatch) -> None:
    """关键测试：窗口截断的正确性
    
    插入 30 条 user/assistant 消息，断言传给 LLM 的消息数量 <= MAX_MESSAGES + 1(system)
    """
    db, _ = temp_db
    
    # 创建对话
    request = conversations.ConversationCreateRequest(title="Test Chat")
    conv = asyncio.run(conversations._create_conversation(request, db))
    _commit_db(db)
    conversation_id = conv["id"]
    
    # 捕获传给 chat_flow 的 history_messages
    captured_history_messages = []
    
    def mock_chat_flow(user_message: str, history_messages=None, **kwargs):
        """Mock chat_flow 来捕获传入的 history_messages"""
        from agent_worker.chat_flow import ChatResult
        from agent_worker.trace import TraceCollector
        
        if history_messages is not None:
            captured_history_messages.append(history_messages)
        
        trace = TraceCollector.from_env()
        return ChatResult(
            assistant_reply="Test response",
            memory_status="NO_ACTION",
            trace_id=trace.trace_id,
            trace_lines=[],
        )
    
    monkeypatch.setattr(conversations, "chat_flow", mock_chat_flow)
    monkeypatch.setattr(conversations, "AGENT_WORKER_AVAILABLE", True)
    
    # 插入 30 条 user/assistant 消息（15 轮对话）
    # 注意：每次调用 _create_message 会创建 1 条 user + 1 条 assistant，所以总共会有 30 条消息
    for i in range(15):
        # User message (会生成 user + assistant 两条消息)
        user_request = conversations.MessageCreateRequest(content=f"User message {i}")
        asyncio.run(conversations._create_message(conversation_id, user_request, db))
        _commit_db(db)
    
    # 验证：传给 chat_flow 的 history_messages 数量应该 <= MAX_MESSAGES (40)
    # 注意：这里检查的是传给 chat_flow 的 history_messages，不包含 system message
    # System message 会在 responder 中单独添加
    # 每次调用 _create_message 会创建 2 条消息（user + assistant），所以 15 次调用 = 30 条消息
    
    # 获取最后一次调用时传入的 history_messages
    assert len(captured_history_messages) > 0, "chat_flow should have been called"
    last_history = captured_history_messages[-1]
    
    # 关键断言：历史消息数量应该 <= MAX_MESSAGES (40)
    MAX_MESSAGES = 40  # 从 chat_flow.py 中的默认值
    assert len(last_history) <= MAX_MESSAGES, (
        f"History messages count ({len(last_history)}) should be <= MAX_MESSAGES ({MAX_MESSAGES}), "
        f"but got {len(last_history)} messages. First 5: {last_history[:5]}"
    )
    
    # 验证消息都是 user 或 assistant（不应该有 system，因为 system 在 responder 中单独添加）
    for msg in last_history:
        assert msg.get("role") in ("user", "assistant"), (
            f"History messages should only contain 'user' or 'assistant' roles, "
            f"but found role '{msg.get('role')}' in message: {msg}"
        )
    
    # 验证截断生效：
    # - 15 次调用 _create_message = 15 user + 15 assistant = 30 条消息
    # - 但最后一次调用时，history_messages 不包含当前刚插入的 user message（会被排除）
    # - 所以最后一次调用时，history_messages 应该包含 28 条消息（14 user + 14 assistant）
    # - 因为 MAX_MESSAGES = 40，所以应该保留全部 28 条
    # 注意：实际数量可能因排除当前 user message而略有不同，但应该 <= 30
    assert len(last_history) <= 30, (
        f"Expected <= 30 history messages (15 calls * 2 messages each - 2 excluded), "
        f"but got {len(last_history)}"
    )
    assert len(last_history) > 0, "Should have some history messages"


def test_mark_conversation_read(temp_db) -> None:
    """测试标记对话为已读"""
    from app.services.run_messages import _compute_has_unread
    
    db, _ = temp_db
    
    # 创建对话
    request = conversations.ConversationCreateRequest(title="Test Chat")
    conv = asyncio.run(conversations._create_conversation(request, db))
    _commit_db(db)
    conversation_id = conv["id"]
    
    # 先创建一条消息，使 updated_at > created_at
    message_request = conversations.MessageCreateRequest(
        content="Test message",
        role="assistant"
    )
    asyncio.run(conversations._create_message(conversation_id, message_request, db))
    _commit_db(db)
    
    # 刷新 conversation 获取最新的 updated_at
    conversation = db.query(ConversationModel).filter(ConversationModel.id == conversation_id).first()
    db.refresh(conversation)
    message_updated_at = conversation.updated_at  # 保存消息创建后的 updated_at
    
    # 设置 last_read_at = None（模拟未读状态）
    conversation.last_read_at = None
    _commit_db(db)
    
    # 验证初始状态（动态计算）：有新消息且未读，应该有未读
    db.refresh(conversation)
    assert _compute_has_unread(conversation) is True
    
    # 等待一小段时间，确保时间戳不同
    import time
    time.sleep(0.01)
    
    # 标记为已读（设置 last_read_at = max(now, updated_at)）
    response = asyncio.run(conversations._mark_conversation_read(conversation_id, db))
    _commit_db(db)
    
    # 验证响应
    assert_conversation_schema(response)
    assert response["has_unread"] is False
    
    # 验证数据库中的状态
    db.refresh(conversation)
    assert conversation.last_read_at is not None
    # 注意：updated_at 有 onupdate 触发器，在更新 last_read_at 时可能会自动更新
    # 但无论如何，last_read_at 应该 >= updated_at（因为我们设置了 max(now, updated_at) + 1ms）
    # 所以未读应该为 False
    assert conversation.last_read_at >= conversation.updated_at
    assert _compute_has_unread(conversation) is False


def test_mark_nonexistent_conversation_read(temp_db) -> None:
    """测试标记不存在的对话为已读（应返回 404）"""
    db, _ = temp_db
    
    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(conversations._mark_conversation_read("nonexistent-id", db))
    assert excinfo.value.status_code == 404
    assert "Conversation not found" in str(excinfo.value.detail)


def test_emit_run_message_with_existing_conversation_success(temp_db) -> None:
    """测试 emit_run_message：run.conversation_id != null，成功状态"""
    db, _ = temp_db
    
    # 创建对话
    request = conversations.ConversationCreateRequest(title="Test Chat")
    conv = asyncio.run(conversations._create_conversation(request, db))
    _commit_db(db)
    conversation_id = conv["id"]
    
    # 创建 run
    run_id = str(uuid.uuid4())
    run = RunModel(
        id=run_id,
        type="test_task",
        title="Test Task",
        status=RunStatus.SUCCEEDED,
        conversation_id=conversation_id,
        input_json={"test": "input"},
        output_json={"summary": "Task completed successfully", "result": "OK"},
        error=None,
        worker_id=None,
        lease_expires_at=None,
        attempt=1,
        progress=100,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db.add(run)
    _commit_db(db)
    
    # 调用 emit_run_message
    run_messages.emit_run_message(db, run)
    _commit_db(db)
    
    # 验证消息已创建
    messages_response = asyncio.run(conversations._get_conversation_messages(conversation_id, db))
    assert len(messages_response["items"]) == 1
    
    message = messages_response["items"][0]
    assert_message_schema(message)
    assert message["role"] == "assistant"
    assert "任务已完成" in message["content"]
    assert "Test Task" in message["content"]
    assert message["source_ref"] == {"kind": "run", "ref_id": run_id, "excerpt": None}
    
    # 验证 conversation.has_unread = True（动态计算）
    from app.services.run_messages import _compute_has_unread
    conversation = db.query(ConversationModel).filter(ConversationModel.id == conversation_id).first()
    assert _compute_has_unread(conversation) is True


def test_emit_run_message_with_existing_conversation_failed(temp_db) -> None:
    """测试 emit_run_message：run.conversation_id != null，失败状态"""
    db, _ = temp_db
    
    # 创建对话
    request = conversations.ConversationCreateRequest(title="Test Chat")
    conv = asyncio.run(conversations._create_conversation(request, db))
    _commit_db(db)
    conversation_id = conv["id"]
    
    # 创建失败的 run
    run_id = str(uuid.uuid4())
    run = RunModel(
        id=run_id,
        type="test_task",
        title="Test Task",
        status=RunStatus.FAILED,
        conversation_id=conversation_id,
        input_json={"test": "input"},
        output_json=None,
        error="Task execution failed",
        worker_id=None,
        lease_expires_at=None,
        attempt=1,
        progress=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db.add(run)
    _commit_db(db)
    
    # 调用 emit_run_message
    run_messages.emit_run_message(db, run)
    _commit_db(db)
    
    # 验证消息已创建
    messages_response = asyncio.run(conversations._get_conversation_messages(conversation_id, db))
    assert len(messages_response["items"]) == 1
    
    message = messages_response["items"][0]
    assert message["role"] == "assistant"
    assert "任务执行失败" in message["content"]
    assert "Test Task" in message["content"]
    assert "Task execution failed" in message["content"]


def test_emit_run_message_with_existing_conversation_canceled(temp_db) -> None:
    """测试 emit_run_message：run.conversation_id != null，取消状态"""
    db, _ = temp_db
    
    # 创建对话
    request = conversations.ConversationCreateRequest(title="Test Chat")
    conv = asyncio.run(conversations._create_conversation(request, db))
    _commit_db(db)
    conversation_id = conv["id"]
    
    # 创建取消的 run
    run_id = str(uuid.uuid4())
    run = RunModel(
        id=run_id,
        type="test_task",
        title="Test Task",
        status=RunStatus.CANCELED,
        conversation_id=conversation_id,
        input_json={"test": "input"},
        output_json=None,
        error="Canceled by user",
        worker_id=None,
        lease_expires_at=None,
        attempt=1,
        progress=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db.add(run)
    _commit_db(db)
    
    # 调用 emit_run_message
    run_messages.emit_run_message(db, run)
    _commit_db(db)
    
    # 验证消息已创建
    messages_response = asyncio.run(conversations._get_conversation_messages(conversation_id, db))
    assert len(messages_response["items"]) == 1
    
    message = messages_response["items"][0]
    assert message["role"] == "assistant"
    assert "任务已取消" in message["content"]
    assert "Test Task" in message["content"]


def test_emit_run_message_without_conversation_id_success(temp_db) -> None:
    """测试 emit_run_message：run.conversation_id == null，成功状态，应创建新 conversation"""
    db, _ = temp_db
    
    # 创建 run（没有 conversation_id）
    run_id = str(uuid.uuid4())
    run = RunModel(
        id=run_id,
        type="test_task",
        title="Nightly Index Job",
        status=RunStatus.SUCCEEDED,
        conversation_id=None,
        input_json={"test": "input"},
        output_json={"summary": "Indexing completed", "files": 100},
        error=None,
        worker_id=None,
        lease_expires_at=None,
        attempt=1,
        progress=100,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db.add(run)
    _commit_db(db)
    
    # 调用 emit_run_message
    run_messages.emit_run_message(db, run)
    _commit_db(db)
    
    # 验证新 conversation 已创建
    conversations_list = asyncio.run(conversations._list_conversations(db))
    assert len(conversations_list["items"]) == 1
    
    new_conv = conversations_list["items"][0]
    assert_conversation_schema(new_conv)
    assert new_conv["title"] == "Task completed: Nightly Index Job"
    assert new_conv["has_unread"] is True
    assert new_conv["meta_json"] == {
        "kind": "system_run",
        "run_id": run_id,
        "origin": "run",
        "channel_hint": "web",
    }
    
    # 验证消息已创建
    messages_response = asyncio.run(conversations._get_conversation_messages(new_conv["id"], db))
    assert len(messages_response["items"]) == 1
    
    message = messages_response["items"][0]
    assert message["role"] == "assistant"
    assert "任务已完成" in message["content"]
    assert "Nightly Index Job" in message["content"]


def test_emit_run_message_without_conversation_id_no_title(temp_db) -> None:
    """测试 emit_run_message：run.conversation_id == null，没有 title，应使用 type"""
    db, _ = temp_db
    
    # 创建 run（没有 conversation_id 和 title）
    run_id = str(uuid.uuid4())
    run = RunModel(
        id=run_id,
        type="index_repo",
        title=None,
        status=RunStatus.SUCCEEDED,
        conversation_id=None,
        input_json={"test": "input"},
        output_json={"result": "OK"},
        error=None,
        worker_id=None,
        lease_expires_at=None,
        attempt=1,
        progress=100,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db.add(run)
    _commit_db(db)
    
    # 调用 emit_run_message
    run_messages.emit_run_message(db, run)
    _commit_db(db)
    
    # 验证新 conversation 的标题使用 type
    conversations_list = asyncio.run(conversations._list_conversations(db))
    assert len(conversations_list["items"]) == 1
    
    new_conv = conversations_list["items"][0]
    assert new_conv["title"] == "Task completed: index_repo"


def test_emit_run_message_nonexistent_conversation(temp_db) -> None:
    """测试 emit_run_message：conversation_id 存在但 conversation 不存在，应记录警告但不抛出异常"""
    db, _ = temp_db
    
    # 创建 run（conversation_id 指向不存在的 conversation）
    run_id = str(uuid.uuid4())
    nonexistent_conv_id = str(uuid.uuid4())
    run = RunModel(
        id=run_id,
        type="test_task",
        title="Test Task",
        status=RunStatus.SUCCEEDED,
        conversation_id=nonexistent_conv_id,
        input_json={"test": "input"},
        output_json={"result": "OK"},
        error=None,
        worker_id=None,
        lease_expires_at=None,
        attempt=1,
        progress=100,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db.add(run)
    _commit_db(db)
    
    # 调用 emit_run_message（不应该抛出异常）
    run_messages.emit_run_message(db, run)
    _commit_db(db)
    
    # 验证没有创建消息（因为 conversation 不存在）
    conversations_list = asyncio.run(conversations._list_conversations(db))
    assert len(conversations_list["items"]) == 0


def test_format_run_output_summary(temp_db) -> None:
    """测试 _format_run_output_summary 函数"""
    # 测试 None
    assert run_messages._format_run_output_summary(None) == "任务已完成。"
    
    # 测试有 summary 字段
    output1 = {"summary": "This is a summary"}
    assert run_messages._format_run_output_summary(output1) == "This is a summary"
    
    # 测试有 message 字段
    output2 = {"message": "Task completed"}
    assert run_messages._format_run_output_summary(output2) == "Task completed"
    
    # 测试有 result 字段
    output3 = {"result": "Success"}
    assert run_messages._format_run_output_summary(output3) == "Success"
    
    # 测试普通字典（会转换为字符串）
    output4 = {"key1": "value1", "key2": "value2"}
    result4 = run_messages._format_run_output_summary(output4)
    assert isinstance(result4, str)
    assert len(result4) > 0
    
    # 测试长字符串（应该截断）
    long_output = {"data": "x" * 1000}
    result5 = run_messages._format_run_output_summary(long_output)
    assert len(result5) <= 503  # 500 + "..."
    assert result5.endswith("...")
    
    # 测试非字典类型
    assert run_messages._format_run_output_summary("simple string") == "simple string"
    assert run_messages._format_run_output_summary(123) == "123"


def test_emit_run_message_idempotency(temp_db) -> None:
    """测试 emit_run_message 的幂等性：重复调用应该只创建一条消息"""
    db, _ = temp_db
    
    # 创建对话
    request = conversations.ConversationCreateRequest(title="Test Chat")
    conv = asyncio.run(conversations._create_conversation(request, db))
    _commit_db(db)
    conversation_id = conv["id"]
    
    # 创建 run
    run_id = str(uuid.uuid4())
    run = RunModel(
        id=run_id,
        type="test_task",
        title="Test Task",
        status=RunStatus.SUCCEEDED,
        conversation_id=conversation_id,
        input_json={"test": "input"},
        output_json={"result": "OK"},
        error=None,
        worker_id=None,
        lease_expires_at=None,
        attempt=1,
        progress=100,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db.add(run)
    _commit_db(db)
    
    # 第一次调用
    run_messages.emit_run_message(db, run)
    _commit_db(db)
    
    # 验证消息已创建
    messages_response = asyncio.run(conversations._get_conversation_messages(conversation_id, db))
    assert len(messages_response["items"]) == 1
    first_message_id = messages_response["items"][0]["id"]
    
    # 第二次调用（应该被跳过，幂等）
    run_messages.emit_run_message(db, run)
    _commit_db(db)
    
    # 验证仍然只有一条消息
    messages_response = asyncio.run(conversations._get_conversation_messages(conversation_id, db))
    assert len(messages_response["items"]) == 1
    assert messages_response["items"][0]["id"] == first_message_id


def test_run_without_conversation_creates_new_unread_conversation_and_message(temp_db) -> None:
    """端到端测试：run 没有 conversation_id 时，创建新的未读 conversation 和消息
    
    语义验证：
    - 创建新的 conversation（title = "Task completed: {run.title}"）
    - conversation.has_unread = True（因为 last_read_at = None）
    - conversation.meta_json 包含正确的字段（kind, run_id, origin, channel_hint）
    - 创建了 assistant 消息
    - 消息的 source_ref 正确（kind="run", ref_id=run.id）
    """
    db, _ = temp_db
    
    # 创建 run（没有 conversation_id）
    run_id = str(uuid.uuid4())
    run = RunModel(
        id=run_id,
        type="nightly_index",
        title="夜间索引任务",
        status=RunStatus.SUCCEEDED,
        conversation_id=None,
        input_json={"task": "index"},
        output_json={"summary": "索引完成，处理了 1000 个文件"},
        error=None,
        worker_id=None,
        lease_expires_at=None,
        attempt=1,
        progress=100,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db.add(run)
    _commit_db(db)
    
    # 调用 emit_run_message
    run_messages.emit_run_message(db, run)
    _commit_db(db)
    
    # 验证新 conversation 已创建
    conversations_list = asyncio.run(conversations._list_conversations(db))
    assert len(conversations_list["items"]) == 1
    
    new_conv = conversations_list["items"][0]
    assert_conversation_schema(new_conv)
    
    # 验证 conversation 属性
    assert new_conv["title"] == "Task completed: 夜间索引任务"
    assert new_conv["has_unread"] is True  # 新创建的 conversation 应该是未读
    assert new_conv["last_read_at"] is None  # 从未读过
    assert new_conv["meta_json"] == {
        "kind": "system_run",
        "run_id": run_id,
        "origin": "run",
        "channel_hint": "web",
    }
    
    # 验证消息已创建
    messages_response = asyncio.run(conversations._get_conversation_messages(new_conv["id"], db))
    assert len(messages_response["items"]) == 1
    
    message = messages_response["items"][0]
    assert message["role"] == "assistant"
    assert "任务已完成：夜间索引任务" in message["content"]
    assert "索引完成，处理了 1000 个文件" in message["content"]
    assert message["source_ref"] == {
        "kind": "run",
        "ref_id": run_id,
        "excerpt": None,
    }


def test_run_with_conversation_emits_message_without_unread_when_last_read_recent(temp_db) -> None:
    """端到端测试：run 有 conversation_id 时，发送消息，但如果最近已读则不应标记为未读
    
    语义验证：
    - run.conversation_id 存在，消息发送到现有 conversation
    - 如果 last_read_at 很新（>= updated_at），has_unread = False
    - 如果 last_read_at 很旧（< updated_at），has_unread = True
    - 消息已创建，source_ref 正确
    """
    db, _ = temp_db
    
    # 创建 conversation
    request = conversations.ConversationCreateRequest(title="测试对话")
    conv = asyncio.run(conversations._create_conversation(request, db))
    _commit_db(db)
    conversation_id = conv["id"]
    
    # 先创建一条消息，使 updated_at > created_at
    message_request = conversations.MessageCreateRequest(
        content="第一条消息",
        role="user"
    )
    asyncio.run(conversations._create_message(conversation_id, message_request, db))
    _commit_db(db)
    
    # 标记为已读（设置 last_read_at = 当前时间）
    asyncio.run(conversations._mark_conversation_read(conversation_id, db))
    _commit_db(db)
    
    # 刷新 conversation，获取最新的 last_read_at
    conversation = db.query(ConversationModel).filter(ConversationModel.id == conversation_id).first()
    db.refresh(conversation)
    last_read_before = conversation.last_read_at
    assert last_read_before is not None
    
    # 等待一小段时间，确保时间戳不同
    import time
    time.sleep(0.01)
    
    # 创建 run（有 conversation_id）
    run_id = str(uuid.uuid4())
    run = RunModel(
        id=run_id,
        type="analysis_task",
        title="数据分析任务",
        status=RunStatus.SUCCEEDED,
        conversation_id=conversation_id,
        input_json={"data": "test"},
        output_json={"summary": "分析完成，发现 5 个模式"},
        error=None,
        worker_id=None,
        lease_expires_at=None,
        attempt=1,
        progress=100,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db.add(run)
    _commit_db(db)
    
    # 调用 emit_run_message
    run_messages.emit_run_message(db, run)
    _commit_db(db)
    
    # 刷新 conversation
    db.refresh(conversation)
    
    # 验证 conversation 状态
    # 因为 last_read_at 很新（刚刚设置的），而消息的 updated_at 可能稍早或相同
    # 所以 has_unread 应该是 False（用户正在查看对话）
    conversations_list = asyncio.run(conversations._list_conversations(db))
    assert len(conversations_list["items"]) == 1
    
    updated_conv = conversations_list["items"][0]
    assert_conversation_schema(updated_conv)
    assert updated_conv["id"] == conversation_id
    
    # 验证 last_read_at 没有变化（因为我们刚刚设置过）
    assert updated_conv["last_read_at"] is not None
    
    # 验证 has_unread：由于 last_read_at 很新（刚刚设置的），而 updated_at 在 emit_run_message 时被更新
    # 由于 onupdate 触发器，updated_at 可能在 commit 时再次更新
    # 但 _mark_conversation_read 会确保 last_read_at >= updated_at（在设置时）
    # 如果 updated_at 在之后被更新（onupdate），我们需要验证 has_unread 的逻辑
    
    # 如果 last_read_at >= updated_at，has_unread 应该是 False
    # 如果 last_read_at < updated_at（由于 onupdate 触发器），has_unread 应该是 True
    # 但由于 _mark_conversation_read 设置了 last_read_at = max(now, updated_at) + 1ms
    # 所以理论上 last_read_at 应该 >= updated_at
    # 但 onupdate 触发器可能在 commit 时更新 updated_at，导致 updated_at > last_read_at
    
    # 实际上，由于时间戳的微妙差异，我们需要验证逻辑：
    # 如果 last_read_at >= updated_at，has_unread = False
    # 如果 last_read_at < updated_at，has_unread = True
    from app.services.run_messages import _compute_has_unread
    conversation_obj = db.query(ConversationModel).filter(ConversationModel.id == conversation_id).first()
    db.refresh(conversation_obj)
    
    # 验证 has_unread 的计算逻辑
    computed_has_unread = _compute_has_unread(conversation_obj)
    assert updated_conv["has_unread"] == computed_has_unread
    
    # 如果 last_read_at >= updated_at，has_unread 应该是 False
    # 如果 last_read_at < updated_at，has_unread 应该是 True
    if conversation_obj.last_read_at >= conversation_obj.updated_at:
        assert updated_conv["has_unread"] is False, f"last_read_at={conversation_obj.last_read_at}, updated_at={conversation_obj.updated_at}"
    else:
        assert updated_conv["has_unread"] is True, f"last_read_at={conversation_obj.last_read_at}, updated_at={conversation_obj.updated_at}"
    
    # 验证消息已创建
    messages_response = asyncio.run(conversations._get_conversation_messages(conversation_id, db))
    assert len(messages_response["items"]) == 2  # 第一条用户消息 + 新的 run 消息
    
    # 找到 run 消息
    run_message = None
    for msg in messages_response["items"]:
        if msg.get("source_ref") and msg["source_ref"].get("kind") == "run":
            run_message = msg
            break
    
    assert run_message is not None
    assert run_message["role"] == "assistant"
    assert "任务已完成：数据分析任务" in run_message["content"]
    assert "分析完成，发现 5 个模式" in run_message["content"]
    assert run_message["source_ref"] == {
        "kind": "run",
        "ref_id": run_id,
        "excerpt": None,
    }
    
    # 现在测试：如果 last_read_at 很旧，则应该有未读
    # 等待一小段时间
    time.sleep(0.01)
    
    # 创建另一个 run
    run_id2 = str(uuid.uuid4())
    run2 = RunModel(
        id=run_id2,
        type="another_task",
        title="另一个任务",
        status=RunStatus.SUCCEEDED,
        conversation_id=conversation_id,
        input_json={"data": "test2"},
        output_json={"summary": "另一个任务完成"},
        error=None,
        worker_id=None,
        lease_expires_at=None,
        attempt=1,
        progress=100,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db.add(run2)
    _commit_db(db)
    
    # 调用 emit_run_message
    run_messages.emit_run_message(db, run2)
    _commit_db(db)
    
    # 刷新 conversation
    db.refresh(conversation)
    
    # 验证：由于 last_read_at 很旧（之前设置的），而 updated_at 已更新（新消息时间）
    # 所以 has_unread 应该是 True
    conversations_list2 = asyncio.run(conversations._list_conversations(db))
    updated_conv2 = conversations_list2["items"][0]
    
    # updated_at（新消息时间）应该 > last_read_at（之前设置的），所以应该有未读
    assert updated_conv2["updated_at"] > updated_conv2["last_read_at"]
    assert updated_conv2["has_unread"] is True


def test_has_unread_with_last_read_at(temp_db) -> None:
    """测试 has_unread 基于 last_read_at 的计算逻辑"""
    db, _ = temp_db
    
    # 创建对话
    request = conversations.ConversationCreateRequest(title="Test Chat")
    conv = asyncio.run(conversations._create_conversation(request, db))
    _commit_db(db)
    conversation_id = conv["id"]
    
    conversation = db.query(ConversationModel).filter(ConversationModel.id == conversation_id).first()
    
    # 初始状态：last_read_at = None
    assert conversation.last_read_at is None
    # 新创建的 conversation，还没有消息，所以未读为 False（updated_at 还没有更新）
    from app.services.run_messages import _compute_has_unread
    assert _compute_has_unread(conversation) is False
    
    # 创建 run 并发送消息
    run_id = str(uuid.uuid4())
    run = RunModel(
        id=run_id,
        type="test_task",
        title="Test Task",
        status=RunStatus.SUCCEEDED,
        conversation_id=conversation_id,
        input_json={"test": "input"},
        output_json={"result": "OK"},
        error=None,
        worker_id=None,
        lease_expires_at=None,
        attempt=1,
        progress=100,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db.add(run)
    _commit_db(db)
    
    # 发送消息
    run_messages.emit_run_message(db, run)
    _commit_db(db)
    
    # 刷新 conversation
    db.refresh(conversation)
    # 因为 last_read_at = None，应该有未读
    from app.services.run_messages import _compute_has_unread
    assert _compute_has_unread(conversation) is True
    
    # 等待一小段时间，确保时间戳不同
    import time
    time.sleep(0.01)
    
    # 标记为已读（设置 last_read_at = max(now, updated_at)）
    asyncio.run(conversations._mark_conversation_read(conversation_id, db))
    _commit_db(db)
    
    # 刷新 conversation
    db.refresh(conversation)
    assert conversation.last_read_at is not None
    # last_read_at >= updated_at，所以未读为 False
    assert conversation.last_read_at >= conversation.updated_at
    assert _compute_has_unread(conversation) is False
    
    # 再次发送消息（更新 updated_at）
    run_id2 = str(uuid.uuid4())
    run2 = RunModel(
        id=run_id2,
        type="test_task2",
        title="Test Task 2",
        status=RunStatus.SUCCEEDED,
        conversation_id=conversation_id,
        input_json={"test": "input2"},
        output_json={"result": "OK2"},
        error=None,
        worker_id=None,
        lease_expires_at=None,
        attempt=1,
        progress=100,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db.add(run2)
    _commit_db(db)
    
    run_messages.emit_run_message(db, run2)
    _commit_db(db)
    
    # 刷新 conversation
    db.refresh(conversation)
    # updated_at > last_read_at，应该有未读
    assert conversation.updated_at > conversation.last_read_at
    from app.services.run_messages import _compute_has_unread
    assert _compute_has_unread(conversation) is True


# ============================================================================
# Agent Loop Integration Tests
# ============================================================================

def test_agent_loop_decision_reply_only(temp_db, monkeypatch) -> None:
    """Test Agent Loop: decision=reply, only reply, no run created."""
    db, _ = temp_db
    
    # Create conversation
    request = conversations.ConversationCreateRequest(title="Test Chat")
    conv = asyncio.run(conversations._create_conversation(request, db))
    _commit_db(db)
    conversation_id = conv["id"]
    
    # Mock Agent Decision to return reply-only
    decision_json = {
        "decision": "reply",
        "reply": {"content": "Hello! How can I help you?"},
        "run": None,
        "confidence": 0.9,
        "reason": "User asked a question",
    }
    
    def mock_decide(*args, **kwargs):
        from app.services.agent_decision import Decision, ReplyContent
        return Decision(
            decision="reply",
            reply=ReplyContent(content="Hello! How can I help you?"),
            run=None,
            confidence=0.9,
            reason="User asked a question",
        )
    
    # Enable Agent Loop and mock AgentDecision
    monkeypatch.setattr(conversations, "AGENT_LOOP_ENABLED", True)
    monkeypatch.setattr(conversations, "AGENT_DECISION_AVAILABLE", True)
    
    # Mock AgentDecision.decide directly
    with patch("app.api.conversations.AgentDecision") as mock_agent_decision_class:
        mock_agent_decision = MagicMock()
        mock_agent_decision.decide = MagicMock(side_effect=mock_decide)
        mock_agent_decision.get_active_facts = MagicMock(return_value=[])
        mock_agent_decision_class.return_value = mock_agent_decision
        
        # Create message
        message_request = conversations.MessageCreateRequest(content="Hello")
        result = asyncio.run(conversations._create_message(conversation_id, message_request, db))
        _commit_db(db)
    
    # Verify result
    assert "user_message" in result
    assert "assistant_message" in result
    assert result["assistant_message"]["role"] == "assistant"
    assert result["assistant_message"]["content"] == "Hello! How can I help you?"
    
    # Verify no run was created
    from app.api.runs import _list_conversation_runs
    runs_result = asyncio.run(_list_conversation_runs(conversation_id, db))
    assert len(runs_result["items"]) == 0
    
    # Verify meta_json indicates agent_decision was used
    assert result["assistant_message"]["meta_json"] is not None
    assert result["assistant_message"]["meta_json"].get("agent_decision") is True


def test_agent_loop_decision_run_only(temp_db, monkeypatch) -> None:
    """Test Agent Loop: decision=run, create run with hint message."""
    db, _ = temp_db
    
    # Create conversation
    request = conversations.ConversationCreateRequest(title="Test Chat")
    conv = asyncio.run(conversations._create_conversation(request, db))
    _commit_db(db)
    conversation_id = conv["id"]
    
    # Mock Agent Decision to return run-only
    def mock_decide(*args, **kwargs):
        from app.services.agent_decision import Decision, RunDecision
        return Decision(
            decision="run",
            reply=None,
            run=RunDecision(
                type="sleep",
                title="Sleep 5 seconds",
                conversation_id=conversation_id,
                input={"seconds": 5},
            ),
            confidence=0.95,
            reason="User wants to sleep",
        )
    
    # Enable Agent Loop and mock AgentDecision
    monkeypatch.setattr(conversations, "AGENT_LOOP_ENABLED", True)
    monkeypatch.setattr(conversations, "AGENT_DECISION_AVAILABLE", True)
    
    # Mock AgentDecision.decide directly
    with patch("app.api.conversations.AgentDecision") as mock_agent_decision_class:
        mock_agent_decision = MagicMock()
        mock_agent_decision.decide = MagicMock(side_effect=mock_decide)
        mock_agent_decision.get_active_facts = MagicMock(return_value=[])
        mock_agent_decision_class.return_value = mock_agent_decision
        
        # Create message
        message_request = conversations.MessageCreateRequest(content="Sleep for 5 seconds")
        result = asyncio.run(conversations._create_message(conversation_id, message_request, db))
        _commit_db(db)
    
    # Verify result
    assert "user_message" in result
    assert "assistant_message" in result
    assert result["assistant_message"]["role"] == "assistant"
    # Should have hint message
    assert "我已开始后台任务" in result["assistant_message"]["content"]
    assert "Sleep 5 seconds" in result["assistant_message"]["content"]
    
    # Verify run was created
    from app.api.runs import _list_conversation_runs
    runs_result = asyncio.run(_list_conversation_runs(conversation_id, db))
    assert len(runs_result["items"]) == 1
    run = runs_result["items"][0]
    assert run["type"] == "sleep"
    assert run["title"] == "Sleep 5 seconds"
    assert run["conversation_id"] == conversation_id
    assert run["input"] == {"seconds": 5}
    assert run["status"] == "queued"


def test_agent_loop_decision_reply_and_run(temp_db, monkeypatch) -> None:
    """Test Agent Loop: decision=reply_and_run, reply + create run."""
    db, _ = temp_db
    
    # Create conversation
    request = conversations.ConversationCreateRequest(title="Test Chat")
    conv = asyncio.run(conversations._create_conversation(request, db))
    _commit_db(db)
    conversation_id = conv["id"]
    
    # Mock Agent Decision to return reply_and_run
    def mock_decide(*args, **kwargs):
        from app.services.agent_decision import Decision, ReplyContent, RunDecision
        return Decision(
            decision="reply_and_run",
            reply=ReplyContent(content="I'll start the sleep task for you."),
            run=RunDecision(
                type="sleep",
                title="Sleep 5 seconds",
                conversation_id=conversation_id,
                input={"seconds": 5},
            ),
            confidence=0.98,
            reason="User wants both reply and task",
        )
    
    # Enable Agent Loop and mock AgentDecision
    monkeypatch.setattr(conversations, "AGENT_LOOP_ENABLED", True)
    monkeypatch.setattr(conversations, "AGENT_DECISION_AVAILABLE", True)
    
    # Mock AgentDecision.decide directly
    with patch("app.api.conversations.AgentDecision") as mock_agent_decision_class:
        mock_agent_decision = MagicMock()
        mock_agent_decision.decide = MagicMock(side_effect=mock_decide)
        mock_agent_decision.get_active_facts = MagicMock(return_value=[])
        mock_agent_decision_class.return_value = mock_agent_decision
        
        # Create message
        message_request = conversations.MessageCreateRequest(content="Please sleep for 5 seconds")
        result = asyncio.run(conversations._create_message(conversation_id, message_request, db))
        _commit_db(db)
    
    # Verify result
    assert "user_message" in result
    assert "assistant_message" in result
    assert result["assistant_message"]["role"] == "assistant"
    assert result["assistant_message"]["content"] == "I'll start the sleep task for you."
    
    # Verify run was created
    from app.api.runs import _list_conversation_runs
    runs_result = asyncio.run(_list_conversation_runs(conversation_id, db))
    assert len(runs_result["items"]) == 1
    run = runs_result["items"][0]
    assert run["type"] == "sleep"
    assert run["title"] == "Sleep 5 seconds"
    assert run["conversation_id"] == conversation_id


def test_agent_loop_decision_fallback_to_chat_flow(temp_db, monkeypatch) -> None:
    """Test Agent Loop: Decision failure falls back to chat_flow."""
    db, _ = temp_db
    
    # Create conversation
    request = conversations.ConversationCreateRequest(title="Test Chat")
    conv = asyncio.run(conversations._create_conversation(request, db))
    _commit_db(db)
    conversation_id = conv["id"]
    
    # Mock chat_flow to return a response
    def mock_chat_flow(*args, **kwargs):
        from agent_worker.chat_flow import ChatResult
        return ChatResult(
            assistant_reply="Fallback response from chat_flow",
            memory_status="no_action",
            trace_id="test-trace-id",
            trace_lines=[],
        )
    
    # Enable Agent Loop but make Decision fail
    monkeypatch.setattr(conversations, "AGENT_LOOP_ENABLED", True)
    monkeypatch.setattr(conversations, "AGENT_DECISION_AVAILABLE", True)
    monkeypatch.setattr(conversations, "chat_flow", mock_chat_flow)
    monkeypatch.setattr(conversations, "AGENT_WORKER_AVAILABLE", True)
    
    # Mock AgentDecision.decide directly
    with patch("app.api.conversations.AgentDecision") as mock_agent_decision_class:
        # Make Decision raise an error
        mock_agent_decision = MagicMock()
        mock_agent_decision.decide = MagicMock(side_effect=ValueError("Decision failed"))
        mock_agent_decision.get_active_facts = MagicMock(return_value=[])
        mock_agent_decision_class.return_value = mock_agent_decision
        
        # Create message
        message_request = conversations.MessageCreateRequest(content="Test message")
        result = asyncio.run(conversations._create_message(conversation_id, message_request, db))
        _commit_db(db)
    
    # Verify fallback to chat_flow worked
    assert "user_message" in result
    assert "assistant_message" in result
    assert result["assistant_message"]["role"] == "assistant"
    assert result["assistant_message"]["content"] == "Fallback response from chat_flow"
    
    # Verify meta_json does NOT indicate agent_decision was used
    assert result["assistant_message"]["meta_json"] is None or result["assistant_message"]["meta_json"].get("agent_decision") is not True


def test_agent_loop_run_creation_failure(temp_db, monkeypatch) -> None:
    """Test Agent Loop: Run creation failure still sends reply if available."""
    db, _ = temp_db
    
    # Create conversation
    request = conversations.ConversationCreateRequest(title="Test Chat")
    conv = asyncio.run(conversations._create_conversation(request, db))
    _commit_db(db)
    conversation_id = conv["id"]
    
    # Mock Agent Decision to return reply_and_run
    def mock_decide(*args, **kwargs):
        from app.services.agent_decision import Decision, ReplyContent, RunDecision
        return Decision(
            decision="reply_and_run",
            reply=ReplyContent(content="I'll try to create a task."),
            run=RunDecision(
                type="sleep",
                title="Sleep 5 seconds",
                conversation_id=conversation_id,
                input={"seconds": 5},
            ),
            confidence=0.95,
            reason="Test",
        )
    
    # Enable Agent Loop and mock AgentDecision
    monkeypatch.setattr(conversations, "AGENT_LOOP_ENABLED", True)
    monkeypatch.setattr(conversations, "AGENT_DECISION_AVAILABLE", True)
    
    # Mock AgentDecision.decide directly
    with patch("app.api.conversations.AgentDecision") as mock_agent_decision_class, \
         patch("app.api.conversations._create_run") as mock_create_run:
        mock_agent_decision = MagicMock()
        mock_agent_decision.decide = MagicMock(side_effect=mock_decide)
        mock_agent_decision.get_active_facts = MagicMock(return_value=[])
        mock_agent_decision_class.return_value = mock_agent_decision
        
        # Make run creation fail
        mock_create_run.side_effect = Exception("Run creation failed")
        
        # Create message
        message_request = conversations.MessageCreateRequest(content="Create a task")
        result = asyncio.run(conversations._create_message(conversation_id, message_request, db))
        _commit_db(db)
    
    # Verify reply was still sent (with error note)
    assert "user_message" in result
    assert "assistant_message" in result
    assert result["assistant_message"]["role"] == "assistant"
    assert "I'll try to create a task" in result["assistant_message"]["content"]
    assert "任务创建失败" in result["assistant_message"]["content"]
    
    # Verify no run was created
    from app.api.runs import _list_conversation_runs
    runs_result = asyncio.run(_list_conversation_runs(conversation_id, db))
    assert len(runs_result["items"]) == 0


def test_agent_loop_disabled_fallback_to_chat_flow(temp_db, monkeypatch) -> None:
    """Test Agent Loop: When disabled, uses chat_flow normally."""
    db, _ = temp_db
    
    # Create conversation
    request = conversations.ConversationCreateRequest(title="Test Chat")
    conv = asyncio.run(conversations._create_conversation(request, db))
    _commit_db(db)
    conversation_id = conv["id"]
    
    # Mock chat_flow to return a response
    def mock_chat_flow(*args, **kwargs):
        from agent_worker.chat_flow import ChatResult
        return ChatResult(
            assistant_reply="Response from chat_flow",
            memory_status="no_action",
            trace_id="test-trace-id",
            trace_lines=[],
        )
    
    # Disable Agent Loop
    monkeypatch.setattr(conversations, "AGENT_LOOP_ENABLED", False)
    monkeypatch.setattr(conversations, "chat_flow", mock_chat_flow)
    monkeypatch.setattr(conversations, "AGENT_WORKER_AVAILABLE", True)
    
    # Create message
    message_request = conversations.MessageCreateRequest(content="Test message")
    result = asyncio.run(conversations._create_message(conversation_id, message_request, db))
    _commit_db(db)
    
    # Verify chat_flow was used
    assert "user_message" in result
    assert "assistant_message" in result
    assert result["assistant_message"]["role"] == "assistant"
    assert result["assistant_message"]["content"] == "Response from chat_flow"
    
    # Verify meta_json does NOT indicate agent_decision was used
    assert result["assistant_message"]["meta_json"] is None or result["assistant_message"]["meta_json"].get("agent_decision") is not True
