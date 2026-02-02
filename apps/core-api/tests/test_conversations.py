import asyncio
import os
import tempfile
import uuid
from datetime import datetime

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import sessionmaker

from app.api import conversations
from memory.db import Base, ConversationModel, MessageModel
from memory.schemas import MessageRole
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
    }
    assert set(msg.keys()) == expected
    assert isinstance(msg["id"], str)
    assert isinstance(msg["conversation_id"], str)
    assert msg["role"] in ["user", "assistant", "system"]
    assert isinstance(msg["content"], str)
    assert isinstance(msg["created_at"], str)  # ISO format string
    # source_ref and meta_json can be None or dict


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
