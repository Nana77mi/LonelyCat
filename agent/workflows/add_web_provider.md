---
# Workflow: Add Web Search Provider
workflow_id: "add_web_provider"
workflow_type: "feature_implementation"
phase_requirement: "Phase 1+ (requires WriteGate)"
risk_level: "MEDIUM"
estimated_time: "2-3 hours"
requires_approval: true

# Prerequisites
prerequisites:
  - "WriteGate operational (Phase 1)"
  - "New provider API key obtained"
  - "Provider API documented"
  - "Test environment available"

# Affected Components
affected_components:
  - "apps/agent-worker/worker/tools/web_backends/<provider>.py"
  - "apps/agent-worker/worker/tools/web_provider.py"
  - "apps/core-api/app/api/settings.py"
  - "apps/agent-worker/tests/test_<provider>_backend.py"
  - "docs/websearch/providers/<provider>.md"

---

# Add Web Search Provider Workflow

> **Purpose**: Integrate a new web search backend into LonelyCat's multi-provider search system
> **Inference Note**: This workflow was derived from architecture.md analysis, not hardcoded

---

## 🎯 Objective

Add support for a new web search provider (e.g., Bing, Google, SerpAPI) while maintaining:
- Existing provider compatibility
- Settings merge logic (Defaults ← Env ← DB)
- Sandbox isolation (if needed)
- Audit trail

---

## 📋 Pre-Flight Checks

### 1. Verify Prerequisites
```yaml
- [ ] New provider API key available
- [ ] API rate limits known (requests/minute)
- [ ] Response format documented
- [ ] Error codes documented
```

### 2. Check Existing Patterns
```bash
# Read similar implementations
Read apps/agent-worker/worker/tools/web_backends/ddg_html.py
Read apps/agent-worker/worker/tools/web_backends/baidu_html.py
```

### 3. Policy Check
```yaml
# From agent/policies/default.yaml
- Operation: modify_code
- Risk Level: write (L1)
- Approval: WriteGate required ✓
```

---

## 🔨 Implementation Steps

### Step 1: Create Backend Implementation

**File**: `apps/agent-worker/worker/tools/web_backends/<provider_name>.py`

**Required Interface** (from architecture):
```python
from typing import List, Dict, Any
from .base import WebBackend, SearchResult

class NewProviderBackend(WebBackend):
    """
    Backend for <Provider Name> search API.

    Rate Limits: X requests/minute
    Requires: API_KEY via settings
    """

    def search(
        self,
        query: str,
        settings: Dict[str, Any],
        max_results: int = 10
    ) -> List[SearchResult]:
        """
        Execute search query.

        Args:
            query: Search query string
            settings: Provider-specific config (api_key, timeout, etc.)
            max_results: Maximum results to return

        Returns:
            List of SearchResult objects

        Raises:
            RateLimitError: If quota exceeded
            APIError: If provider returns error
            TimeoutError: If request times out
        """
        # Implementation here
        pass
```

**Key Points**:
- Inherit from `WebBackend` base class
- Handle rate limiting gracefully
- Return normalized `SearchResult` objects
- Sanitize query (prevent injection)
- Handle timeout (from settings.timeout_ms)

**WriteGate**:
```yaml
ChangePlan:
  objective: "Create backend for <Provider> search"
  affected_files:
    - "apps/agent-worker/worker/tools/web_backends/<provider>.py"
  risk_assessment: "LOW (new file, no existing logic modified)"
  rollback_plan: "Delete file"
```

---

### Step 2: Register in WebProvider

**File**: `apps/agent-worker/worker/tools/web_provider.py`

**Changes Required**:
```python
# Add import
from .web_backends.new_provider import NewProviderBackend

# Register in _get_backend()
def _get_backend(backend_name: str, settings: dict):
    backends = {
        "ddg_html": DdgHtmlBackend,
        "baidu_html": BaiduHtmlBackend,
        "searxng": SearxngBackend,
        "bocha": BochaBackend,
        "new_provider": NewProviderBackend,  # Add here
        "stub": StubBackend,
    }
    # ...
```

**WriteGate**:
```yaml
ChangePlan:
  objective: "Register new provider in WebProvider"
  affected_files:
    - "apps/agent-worker/worker/tools/web_provider.py"
  risk_assessment: "MEDIUM (modifies routing logic)"
  rollback_plan: "Git revert + remove provider entry"
  tests_required: true
```

---

### Step 3: Add Settings Schema

**File**: `apps/core-api/app/api/settings.py`

**Changes Required**:

#### A. Default Settings
```python
def _default_settings():
    return {
        # ... existing ...
        "web": {
            "providers": {
                "new_provider": {
                    "enabled": False,  # Disabled by default
                    "api_key": "",
                    "base_url": "https://api.provider.com/v1/search",
                    "timeout_ms": 15000,
                    "max_results_default": 10,
                    "rate_limit_per_minute": 60
                }
            }
        }
    }
```

#### B. Environment Variable Mapping
```python
def _env_settings():
    # Add mappings
    "NEW_PROVIDER_API_KEY": "web.providers.new_provider.api_key",
    "NEW_PROVIDER_BASE_URL": "web.providers.new_provider.base_url",
```

**WriteGate**:
```yaml
ChangePlan:
  objective: "Add settings schema for new provider"
  affected_files:
    - "apps/core-api/app/api/settings.py"
  risk_assessment: "MEDIUM (config changes affect all users)"
  rollback_plan: "Remove settings entries + restart service"
  verification:
    - "GET /settings returns new provider config"
    - "Env var mapping works"
```

---

### Step 4: Write Tests

**File**: `apps/agent-worker/tests/test_<provider>_backend.py`

**Required Test Cases**:
```python
import pytest
from worker.tools.web_backends.new_provider import NewProviderBackend

def test_search_basic():
    """Basic search returns results."""
    backend = NewProviderBackend()
    results = backend.search("python tutorial", settings={...})
    assert len(results) > 0
    assert results[0].title
    assert results[0].url

def test_search_empty_query():
    """Empty query returns empty results."""
    backend = NewProviderBackend()
    results = backend.search("", settings={...})
    assert len(results) == 0

def test_search_api_error(mocker):
    """API error raises APIError."""
    mocker.patch("httpx.get", side_effect=httpx.HTTPError)
    backend = NewProviderBackend()
    with pytest.raises(APIError):
        backend.search("test", settings={...})

def test_search_timeout(mocker):
    """Timeout raises TimeoutError."""
    mocker.patch("httpx.get", side_effect=httpx.TimeoutException)
    backend = NewProviderBackend()
    with pytest.raises(TimeoutError):
        backend.search("test", settings={...})

def test_search_rate_limit(mocker):
    """Rate limit returns 429 → RateLimitError."""
    mocker.patch("httpx.get", return_value=MockResponse(429))
    backend = NewProviderBackend()
    with pytest.raises(RateLimitError):
        backend.search("test", settings={...})
```

**Run Tests**:
```bash
.\scripts\test-py.ps1
# Or on Linux/Mac:
make test-agent-worker
```

---

### Step 5: Update Documentation

**File**: `docs/websearch/providers/<provider>.md`

**Required Sections**:
```markdown
# <Provider Name> Search Backend

## Overview
- Provider: <Name>
- API Docs: <URL>
- Rate Limits: X requests/minute
- Requires: API Key

## Setup

### 1. Get API Key
- Visit <URL>
- Create account
- Generate API key

### 2. Configure LonelyCat
```bash
# Via environment variable
export NEW_PROVIDER_API_KEY="your_key_here"

# Or in .env
NEW_PROVIDER_API_KEY=your_key_here
```

### 3. Enable Provider
```bash
# Set as default backend
export WEB_SEARCH_BACKEND=new_provider
```

## Configuration

| Setting | Env Var | Default | Description |
|---------|---------|---------|-------------|
| enabled | - | false | Enable provider |
| api_key | NEW_PROVIDER_API_KEY | "" | API key |
| base_url | NEW_PROVIDER_BASE_URL | ... | API endpoint |
| timeout_ms | - | 15000 | Request timeout |

## Limitations
- Rate limit: X/min
- No support for: <features>
- Known issues: <issues>
```

---

### Step 6: Integration Testing

**Manual Verification**:
```bash
# 1. Set environment
export WEB_SEARCH_BACKEND=new_provider
export NEW_PROVIDER_API_KEY=your_key

# 2. Start services
.\scripts\up.ps1  # Windows
# or: make up   # Linux/Mac

# 3. Test via API
curl http://localhost:5173/api/tools/web.search \
  -H "Content-Type: application/json" \
  -d '{"query": "python tutorial"}'

# 4. Check logs
Get-Content .pids/agent-worker.log -Tail 50
```

**Expected Result**:
```json
{
  "results": [
    {"title": "...", "url": "...", "snippet": "..."}
  ],
  "backend_used": "new_provider",
  "cache_hit": false
}
```

---

## 🔍 Verification Checklist

- [ ] Backend implements `search()` correctly
- [ ] Provider registered in WebProvider
- [ ] Settings schema added (defaults + env)
- [ ] All tests pass (unit + integration)
- [ ] Documentation complete
- [ ] API key secured (not committed to git)
- [ ] Rate limiting handled gracefully
- [ ] Error messages clear and actionable

---

## 🚨 Common Issues

### Issue 1: API Key Not Found
**Symptom**: `KeyError: 'api_key'` in logs
**Cause**: Settings not merged correctly
**Fix**:
```bash
# Check settings endpoint
curl http://localhost:5173/settings | jq '.web.providers.new_provider'
# Verify env var is set
echo $NEW_PROVIDER_API_KEY
```

### Issue 2: Timeout on Every Request
**Symptom**: All searches timeout after 15s
**Cause**: Provider's API slow or unreachable
**Fix**:
```python
# Increase timeout in settings
{
  "web.providers.new_provider.timeout_ms": 30000
}
```

### Issue 3: Rate Limit Exceeded
**Symptom**: `RateLimitError` after few requests
**Cause**: Free tier limit reached
**Fix**: Upgrade to paid plan or implement request queuing

---

## 🔄 Rollback Procedure

If integration fails:

1. **Revert Code Changes**
   ```bash
   git log --oneline -10  # Find commit before changes
   git revert <commit_sha>
   ```

2. **Remove Settings**
   ```bash
   # Remove env vars
   unset NEW_PROVIDER_API_KEY
   unset WEB_SEARCH_BACKEND
   ```

3. **Restart Services**
   ```bash
   .\scripts\down.ps1
   .\scripts\up.ps1
   ```

4. **Verify Rollback**
   ```bash
   # Should use previous backend (e.g., ddg_html)
   curl http://localhost:5173/settings | jq '.web.search.backend'
   ```

---

## 📚 Related Docs

- [architecture.md](../architecture.md) → EXECUTION MODEL → Tool Catalog
- [policies/default.yaml](../policies/default.yaml) → writegate_rules
- [docs/websearch/](../../docs/websearch/) → Other provider examples

---

**Version**: 1.0.0
**Last Updated**: 2026-02-09
**Inferred From**: architecture.md analysis (emergent workflow)
