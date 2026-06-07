#!/usr/bin/env python3
"""
Mavis Brain Server - MCP-like Long-term Memory with Evolution
Based on Mem0 architecture, optimized for self-hosted NAS deployment

Key Features:
- Add-only memory (accumulate, never overwrite)
- Multi-signal search (content + category + entity)
- Entity-based organization (user_id, agent_id, run_id)
- Evolution tracking (learns from interactions)
- Cross-device sync
- Skills system (learned abilities)
"""

import os
import json
import uuid
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, asdict, field
from enum import Enum
import sqlite3
import re

from fastapi import FastAPI, HTTPException, Header, Body, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn

# Configuration
DATA_DIR = Path.home() / "mavis-brain"
DB_PATH = DATA_DIR / "brain.db"
API_KEY_FILE = DATA_DIR / ".apikey"
STORAGE_DIR = DATA_DIR / "memories"

DATA_DIR.mkdir(parents=True, exist_ok=True)
STORAGE_DIR.mkdir(parents=True, exist_ok=True)

def get_db():
    """Get database connection with proper settings"""
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn

def init_db():
    """Initialize database"""
    conn = get_db()
    c = conn.cursor()
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS memories (
            id TEXT PRIMARY KEY, user_id TEXT, agent_id TEXT, run_id TEXT,
            category TEXT DEFAULT 'general', memory_type TEXT DEFAULT 'fact',
            content TEXT NOT NULL, raw_content TEXT,
            confidence REAL DEFAULT 1.0, importance REAL DEFAULT 0.5,
            source TEXT DEFAULT 'manual', tags TEXT DEFAULT '[]',
            entities TEXT DEFAULT '[]', created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL, last_accessed TEXT,
            access_count INTEGER DEFAULT 0, parent_id TEXT,
            metadata TEXT, version INTEGER DEFAULT 1
        )
    ''')
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS user_profiles (
            id TEXT PRIMARY KEY, user_id TEXT UNIQUE NOT NULL, name TEXT,
            preferences TEXT DEFAULT '{}', communication_style TEXT,
            timezone TEXT, habits TEXT DEFAULT '{}',
            personality TEXT DEFAULT '{}', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        )
    ''')
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS skills (
            id TEXT PRIMARY KEY, name TEXT UNIQUE NOT NULL, description TEXT,
            trigger_pattern TEXT, code TEXT, examples TEXT DEFAULT '[]',
            use_count INTEGER DEFAULT 0, success_count INTEGER DEFAULT 0,
            success_rate REAL DEFAULT 0.5, avg_quality REAL DEFAULT 0.5,
            created_at TEXT NOT NULL, last_used TEXT, updated_at TEXT
        )
    ''')
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS evolution_log (
            id TEXT PRIMARY KEY, event_type TEXT NOT NULL, entity_type TEXT,
            entity_id TEXT, trigger TEXT, trigger_context TEXT, result TEXT,
            success BOOLEAN, device_id TEXT, timestamp TEXT NOT NULL, metadata TEXT
        )
    ''')
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS sync_log (
            id TEXT PRIMARY KEY, device_id TEXT NOT NULL, operation TEXT NOT NULL,
            entity_type TEXT, entity_id TEXT, timestamp TEXT NOT NULL,
            synced BOOLEAN DEFAULT 0, conflict_resolved BOOLEAN DEFAULT 0
        )
    ''')
    
    c.execute('CREATE INDEX IF NOT EXISTS idx_memories_user ON memories(user_id)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_memories_category ON memories(category)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_evolution_entity ON evolution_log(entity_type, entity_id)')
    
    conn.commit()
    conn.close()

# Models
class Message(BaseModel):
    role: str
    content: str

class AddMemoryRequest(BaseModel):
    messages: Optional[List[Message]] = None
    content: Optional[str] = None
    user_id: Optional[str] = None
    agent_id: Optional[str] = None
    run_id: Optional[str] = None
    category: Optional[str] = "general"
    memory_type: Optional[str] = "fact"
    source: Optional[str] = "manual"
    tags: Optional[List[str]] = []
    metadata: Optional[dict] = None
    infer: bool = True

class SearchRequest(BaseModel):
    query: str
    user_id: Optional[str] = None
    agent_id: Optional[str] = None
    category: Optional[str] = None
    memory_type: Optional[str] = None
    limit: int = 10

class LogEvolutionRequest(BaseModel):
    event_type: str
    entity_type: Optional[str] = None
    entity_id: Optional[str] = None
    trigger: Optional[str] = None
    success: Optional[bool] = None
    device_id: Optional[str] = None
    metadata: Optional[dict] = None

class AddSkillRequest(BaseModel):
    name: str
    description: str = ""
    trigger_pattern: str = ""
    code: str = ""

# FastAPI App
app = FastAPI(title="Mavis Brain", version="1.0.0")

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

def get_or_create_api_key(x_api_key: Optional[str] = Header(None)) -> str:
    """Get or create API key"""
    if not os.path.exists(API_KEY_FILE):
        key = str(uuid.uuid4())
        API_KEY_FILE.write_text(key)
        return key
    stored_key = API_KEY_FILE.read_text().strip()
    if x_api_key and x_api_key != stored_key:
        raise HTTPException(401, "Invalid API key")
    return stored_key

def extract_entities(content: str) -> List[str]:
    entities = re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b', content)
    return list(set(entities[:5]))

def extract_tags(content: str) -> List[str]:
    keywords = ['prefer', 'like', 'hate', 'always', 'never', 'important', 'remember', 'note']
    return [kw for kw in keywords if kw in content.lower()]

@app.get("/")
async def root():
    return {
        "service": "Mavis Brain", "version": "1.0.0", "status": "running",
        "architecture": "mem0-inspired add-only memory",
        "endpoints": ["/tools/list", "/memory/add", "/memory/search", "/brain/evolve", "/brain/stats", "/skill/*"]
    }

@app.get("/tools/list")
async def list_tools(api_key: str = Header(None)):
    get_or_create_api_key(api_key)
    return {
        "tools": [
            {"name": "memory.add", "description": "Add memories (add-only, accumulates)", "category": "memory"},
            {"name": "memory.search", "description": "Search memories (multi-signal)", "category": "memory"},
            {"name": "memory.get", "description": "Get specific memory by ID", "category": "memory"},
            {"name": "memory.list", "description": "List memories by entity", "category": "memory"},
            {"name": "brain.evolve", "description": "Log evolution event", "category": "brain"},
            {"name": "brain.stats", "description": "Get brain statistics", "category": "brain"},
            {"name": "brain.insights", "description": "Get evolution insights", "category": "brain"},
            {"name": "skill.add", "description": "Add new skill", "category": "skills"},
            {"name": "skill.list", "description": "List all skills", "category": "skills"},
            {"name": "skill.suggest", "description": "Suggest skills for task", "category": "skills"},
            {"name": "user.profile", "description": "Get/update user profile", "category": "user"},
            {"name": "sync.push", "description": "Push changes to brain", "category": "sync"},
            {"name": "sync.pull", "description": "Pull changes from brain", "category": "sync"},
        ]
    }

@app.post("/memory/add")
async def add_memory(req: AddMemoryRequest, api_key: str = Header(None)):
    """Add memory - ADD ONLY, never overwrites existing memories (Mem0-style)"""
    get_or_create_api_key(api_key)
    conn = get_db()
    c = conn.cursor()
    now = datetime.now().isoformat()
    memories_created = []
    
    if req.messages and req.infer:
        for msg in req.messages:
            memory_id = str(uuid.uuid4())
            entities = extract_entities(msg.content)
            tags = extract_tags(msg.content)
            c.execute('''
                INSERT INTO memories 
                (id, user_id, agent_id, run_id, category, memory_type, content, source, tags, entities, created_at, updated_at, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (memory_id, req.user_id, req.agent_id, req.run_id, req.category or "general", req.memory_type or "fact",
                  msg.content, "extracted", json.dumps(tags), json.dumps(entities), now, now, json.dumps({"role": msg.role})))
            memories_created.append(memory_id)
    
    elif req.content:
        memory_id = str(uuid.uuid4())
        entities = extract_entities(req.content)
        tags = req.tags or extract_tags(req.content)
        c.execute('''
            INSERT INTO memories 
            (id, user_id, agent_id, run_id, category, memory_type, content, source, tags, entities, confidence, created_at, updated_at, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (memory_id, req.user_id, req.agent_id, req.run_id, req.category or "general", req.memory_type or "fact",
              req.content, req.source or "manual", json.dumps(tags), json.dumps(entities), 1.0, now, now,
              json.dumps(req.metadata) if req.metadata else None))
        memories_created.append(memory_id)
    
    conn.commit()
    conn.close()
    
    return {"message": "Memory added (add-only)", "status": "success", "memories_created": len(memories_created), "ids": memories_created}

@app.post("/memory/search")
async def search_memory(req: SearchRequest, api_key: str = Header(None)):
    """Multi-signal memory search"""
    get_or_create_api_key(api_key)
    conn = get_db()
    c = conn.cursor()
    
    conditions = []
    params = []
    if req.query:
        search_terms = req.query.lower().split()
        for term in search_terms:
            conditions.append("(LOWER(content) LIKE ? OR LOWER(tags) LIKE ?)")
            params.extend([f"%{term}%", f"%{term}%"])
    if req.user_id:
        conditions.append("user_id = ?")
        params.append(req.user_id)
    if req.category:
        conditions.append("category = ?")
        params.append(req.category)
    
    sql = "SELECT * FROM memories"
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY confidence DESC, created_at DESC LIMIT ?"
    params.append(min(req.limit, 100))
    
    c.execute(sql, params)
    rows = c.fetchall()
    conn.close()
    
    memories = [{"id": r[0], "user_id": r[1], "category": r[4], "memory_type": r[5], "content": r[6],
                 "confidence": r[8], "source": r[10], "tags": json.loads(r[11]) if r[11] else [],
                 "entities": json.loads(r[12]) if r[12] else [], "created_at": r[14], "access_count": r[17]} for r in rows]
    
    return {"results": memories, "count": len(memories), "query": req.query}

@app.get("/memory/{memory_id}")
async def get_memory(memory_id: str, api_key: str = Header(None)):
    get_or_create_api_key(api_key)
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM memories WHERE id = ?", (memory_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "Memory not found")
    now = datetime.now().isoformat()
    c.execute("UPDATE memories SET last_accessed = ?, access_count = access_count + 1 WHERE id = ?", (now, memory_id))
    conn.commit()
    conn.close()
    return {"id": row[0], "user_id": row[1], "agent_id": row[2], "category": row[4], "memory_type": row[5],
            "content": row[6], "confidence": row[8], "source": row[10], "tags": json.loads(row[11]) if row[11] else [],
            "entities": json.loads(row[12]) if row[12] else [], "created_at": row[14], "last_accessed": row[16], "access_count": row[17]}

@app.get("/memory/entity/{entity_type}/{entity_id}")
async def list_entity_memories(entity_type: str, entity_id: str, limit: int = 50, api_key: str = Header(None)):
    get_or_create_api_key(api_key)
    column = "user_id" if entity_type == "user" else "agent_id"
    conn = get_db()
    c = conn.cursor()
    c.execute(f"SELECT * FROM memories WHERE {column} = ? ORDER BY created_at DESC LIMIT ?", (entity_id, limit))
    rows = c.fetchall()
    conn.close()
    return {"entity_type": entity_type, "entity_id": entity_id,
            "memories": [{"id": r[0], "category": r[4], "memory_type": r[5], "content": r[6], "confidence": r[8], "source": r[10], "tags": json.loads(r[11]) if r[11] else [], "created_at": r[14]} for r in rows],
            "count": len(rows)}

@app.post("/brain/evolve")
async def log_evolution(req: LogEvolutionRequest, api_key: str = Header(None)):
    get_or_create_api_key(api_key)
    conn = get_db()
    c = conn.cursor()
    now = datetime.now().isoformat()
    event_id = str(uuid.uuid4())
    c.execute('''
        INSERT INTO evolution_log (id, event_type, entity_type, entity_id, trigger, success, device_id, timestamp, metadata)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (event_id, req.event_type, req.entity_type, req.entity_id, req.trigger, req.success, req.device_id, now,
          json.dumps(req.metadata) if req.metadata else None))
    if req.event_type == "skill_acquired" and req.trigger:
        skill_id = str(uuid.uuid4())
        c.execute("INSERT INTO skills (id, name, description, use_count, created_at) VALUES (?, ?, ?, 0, ?)",
                  (skill_id, req.trigger, req.trigger, now))
    conn.commit()
    conn.close()
    return {"success": True, "event_id": event_id, "timestamp": now}

@app.get("/brain/stats")
async def get_brain_stats(api_key: str = Header(None)):
    get_or_create_api_key(api_key)
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM memories")
    total = c.fetchone()[0]
    c.execute("SELECT memory_type, COUNT(*) FROM memories GROUP BY memory_type")
    by_type = dict(c.fetchall())
    c.execute("SELECT category, COUNT(*) FROM memories GROUP BY category")
    by_cat = dict(c.fetchall())
    c.execute("SELECT COUNT(*) FROM evolution_log")
    evolutions = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM skills")
    skills = c.fetchone()[0]
    c.execute("SELECT AVG(success_rate) FROM skills WHERE use_count > 0")
    avg_success = c.fetchone()[0]
    conn.close()
    return {"total_memories": total, "by_type": by_type, "by_category": by_cat,
            "evolution_events": evolutions, "skills_count": skills, "avg_skill_success_rate": round(avg_success, 2) if avg_success else 0}

@app.get("/brain/insights")
async def get_brain_insights(user_id: Optional[str] = None, api_key: str = Header(None)):
    get_or_create_api_key(api_key)
    conn = get_db()
    c = conn.cursor()
    insights = {}
    if user_id:
        c.execute("SELECT category, COUNT(*) as cnt FROM memories WHERE user_id = ? AND source = 'extracted' GROUP BY category ORDER BY cnt DESC LIMIT 5", (user_id,))
        insights["learned_categories"] = dict(c.fetchall())
    c.execute("SELECT trigger, COUNT(*) as cnt FROM evolution_log WHERE success = 1 GROUP BY trigger ORDER BY cnt DESC LIMIT 10")
    insights["success_patterns"] = dict(c.fetchall())
    c.execute("SELECT name, use_count, success_rate FROM skills ORDER BY use_count DESC LIMIT 10")
    insights["top_skills"] = [{"name": r[0], "uses": r[1], "success_rate": r[2]} for r in c.fetchall()]
    conn.close()
    return insights

@app.post("/skill/add")
async def add_skill(req: AddSkillRequest, api_key: str = Header(None)):
    get_or_create_api_key(api_key)
    conn = get_db()
    c = conn.cursor()
    now = datetime.now().isoformat()
    skill_id = str(uuid.uuid4())
    c.execute("INSERT INTO skills (id, name, description, trigger_pattern, code, created_at) VALUES (?, ?, ?, ?, ?, ?)",
              (skill_id, req.name, req.description, req.trigger_pattern, req.code, now))
    conn.commit()
    conn.close()
    return {"success": True, "id": skill_id, "name": req.name}

@app.get("/skill/list")
async def list_skills(sort: str = "use_count", limit: int = 50, api_key: str = Header(None)):
    get_or_create_api_key(api_key)
    conn = get_db()
    c = conn.cursor()
    order_by = "use_count DESC" if sort == "use_count" else "created_at DESC"
    c.execute(f"SELECT * FROM skills ORDER BY {order_by} LIMIT ?", (limit,))
    rows = c.fetchall()
    conn.close()
    return {"skills": [{"id": r[0], "name": r[1], "description": r[2], "trigger_pattern": r[3], "use_count": r[6], "success_rate": r[8]} for r in rows], "count": len(rows)}

@app.get("/skill/suggest")
async def suggest_skills(task: str, api_key: str = Header(None)):
    get_or_create_api_key(api_key)
    conn = get_db()
    c = conn.cursor()
    task_lower = task.lower()
    c.execute("SELECT * FROM skills WHERE trigger_pattern LIKE ? OR LOWER(description) LIKE ? ORDER BY use_count DESC LIMIT 5",
              (f"%{task_lower}%", f"%{task_lower}%"))
    rows = c.fetchall()
    conn.close()
    return {"task": task, "suggestions": [{"name": r[1], "description": r[2], "use_count": r[6], "success_rate": r[8]} for r in rows]}

@app.post("/skill/{skill_id}/use")
async def record_skill_use(skill_id: str, success: bool = True, quality: float = 0.5, api_key: str = Header(None)):
    get_or_create_api_key(api_key)
    conn = get_db()
    c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute("SELECT use_count, success_count, success_rate, avg_quality FROM skills WHERE id = ?", (skill_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "Skill not found")
    use_count = row[0] + 1
    success_count = row[1] + (1 if success else 0)
    new_success_rate = success_count / use_count
    new_avg_quality = row[3] * 0.9 + quality * 0.1
    c.execute("UPDATE skills SET use_count = ?, success_count = ?, success_rate = ?, avg_quality = ?, last_used = ? WHERE id = ?",
              (use_count, success_count, new_success_rate, new_avg_quality, now, skill_id))
    conn.commit()
    conn.close()
    return {"success": True, "use_count": use_count, "success_rate": round(new_success_rate, 2)}

@app.get("/user/profile/{user_id}")
async def get_user_profile(user_id: str, api_key: str = Header(None)):
    get_or_create_api_key(api_key)
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM user_profiles WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        return {"profile": None}
    return {"profile": {"user_id": row[1], "name": row[2], "preferences": json.loads(row[3]) if row[3] else {},
                        "communication_style": row[4], "timezone": row[5], "habits": json.loads(row[6]) if row[6] else {},
                        "updated_at": row[9]}}

@app.post("/user/profile/{user_id}")
async def update_user_profile(user_id: str, name: Optional[str] = Body(None), preferences: Optional[dict] = Body(None),
                               communication_style: Optional[str] = Body(None), api_key: str = Header(None)):
    get_or_create_api_key(api_key)
    conn = get_db()
    c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute("SELECT id FROM user_profiles WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    if row:
        updates, params = [], []
        if name: updates.append("name = ?"), params.append(name)
        if preferences: updates.append("preferences = ?"), params.append(json.dumps(preferences))
        if communication_style: updates.append("communication_style = ?"), params.append(communication_style)
        updates.append("updated_at = ?"), params.append(now), params.append(row[0])
        c.execute(f"UPDATE user_profiles SET {', '.join(updates)} WHERE id = ?", params)
    else:
        profile_id = str(uuid.uuid4())
        c.execute("INSERT INTO user_profiles (id, user_id, name, preferences, communication_style, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                  (profile_id, user_id, name or user_id, json.dumps(preferences) if preferences else "{}", communication_style or "", now, now))
    conn.commit()
    conn.close()
    return {"success": True, "updated_at": now}

@app.get("/sync/pull")
async def pull_changes(device_id: str, since: Optional[str] = None, user_id: Optional[str] = None, api_key: str = Header(None)):
    get_or_create_api_key(api_key)
    conn = get_db()
    c = conn.cursor()
    if since:
        c.execute("SELECT * FROM memories WHERE updated_at > ? ORDER BY updated_at", (since,))
    elif user_id:
        c.execute("SELECT * FROM memories WHERE user_id = ? ORDER BY updated_at DESC LIMIT 100", (user_id,))
    else:
        c.execute("SELECT * FROM memories ORDER BY updated_at DESC LIMIT 100")
    rows = c.fetchall()
    memories = [{"id": r[0], "user_id": r[1], "category": r[4], "content": r[6], "confidence": r[8], "tags": json.loads(r[11]) if r[11] else [], "created_at": r[14]} for r in rows]
    c.execute("SELECT * FROM evolution_log ORDER BY timestamp DESC LIMIT 50")
    evolutions = [{"id": r[0], "event_type": r[1], "entity_type": r[2], "timestamp": r[9]} for r in c.fetchall()]
    conn.close()
    return {"memories": memories, "evolutions": evolutions, "sync_timestamp": datetime.now().isoformat(), "counts": {"memories": len(memories), "evolutions": len(evolutions)}}

@app.post("/sync/push")
async def push_changes(device_id: str, memories: Optional[List[dict]] = Body(None), api_key: str = Header(None)):
    get_or_create_api_key(api_key)
    conn = get_db()
    c = conn.cursor()
    now = datetime.now().isoformat()
    synced = 0
    if memories:
        for mem in memories:
            c.execute('''INSERT OR REPLACE INTO memories (id, user_id, agent_id, category, memory_type, content, source, tags, confidence, created_at, updated_at)
                         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                      (mem.get('id', str(uuid.uuid4())), mem.get('user_id'), mem.get('agent_id'),
                       mem.get('category', 'general'), mem.get('memory_type', 'fact'), mem.get('content', ''),
                       'sync', json.dumps(mem.get('tags', [])), mem.get('confidence', 1.0), mem.get('created_at', now), now))
            synced += 1
    conn.commit()
    conn.close()
    return {"success": True, "synced": synced, "timestamp": now}

@app.get("/info")
async def server_info(api_key: str = Header(None)):
    get_or_create_api_key(api_key)
    return {"service": "Mavis Brain", "version": "1.0.0", "architecture": "mem0-inspired add-only memory",
            "storage": {"type": "sqlite", "path": str(DB_PATH)},
            "capabilities": {"add_only": True, "multi_signal_search": True, "evolution_tracking": True, "skills_system": True, "cross_device_sync": True},
            "principles": ["Memories accumulate, never overwrite", "Every interaction is a learning opportunity", "Evolution over storage"]}

if __name__ == "__main__":
    init_db()
    print("=" * 50)
    print("Mavis Brain Server")
    print(f"Storage: {DB_PATH}")
    print(f"Port: 5188")
    print(f"Tailscale: 100.76.149.19:5188")
    print("=" * 50)
    uvicorn.run(app, host="0.0.0.0", port=5188, log_level="info")