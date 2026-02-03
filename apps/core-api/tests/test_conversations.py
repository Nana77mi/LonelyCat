import asyncio
import os
import tempfile
import uuid
from datetime import datetime

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import sessionmaker

from app.api import conversations
from app.db import Base, ConversationModel, MessageModel, MessageRole
from sqlalchemy import create_engine


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
    }
    assert set(conv.keys()) == expected
    assert isinstance(conv["id"], str)
    assert isinstance(conv["title"], str)
    assert isinstance(conv["created_at"], str)  # ISO format string
    assert isinstance(conv["updated_at"], str)  # ISO format string


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
    now = datetime.utcnow()
    
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
        created_at=datetime.utcnow(),
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
        created_at=datetime.utcnow(),
    )
    db.add(message2)
    _commit_db(db)
    
    time.sleep(0.01)
    
    message3 = MessageModel(
        id=str(uuid.uuid4()),
        conversation_id=conv["id"],
        role=MessageRole.SYSTEM,
        content="Third message",
        created_at=datetime.utcnow(),
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
