import { useCallback, useEffect, useState } from "react";
import { fetchSettings, updateSettings, type SettingsV0 } from "../api/settings";
import "./SettingsDrawer.css";

type SettingsDrawerProps = {
  isOpen: boolean;
  onClose: () => void;
};

const BACKENDS = [
  { value: "stub" as const, label: "Stub（离线/默认）", desc: "无需额外依赖、CI 稳定；结果为示例数据" },
  { value: "ddg_html" as const, label: "DuckDuckGo HTML（免 Key）", desc: "可能被 403/429 限制；适合默认免费方案" },
  { value: "searxng" as const, label: "SearXNG（自建/可选 Key）", desc: "需要 Base URL；更稳定可控，不要求 Docker" },
];

function getDefaultForm(): Partial<SettingsV0> {
  return {
    version: "settings_v0",
    web: {
      search: {
        backend: "stub",
        timeout_ms: 15000,
      },
    },
  };
}

export const SettingsDrawer = ({ isOpen, onClose }: SettingsDrawerProps) => {
  const [form, setForm] = useState<Partial<SettingsV0>>(getDefaultForm);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showSearxngPassword, setShowSearxngPassword] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchSettings();
      setForm({
        version: data.version,
        web: {
          search: {
            backend: data.web?.search?.backend ?? "stub",
            timeout_ms: data.web?.search?.timeout_ms ?? 15000,
            searxng: data.web?.search?.searxng
              ? {
                  base_url: data.web.search.searxng.base_url ?? "",
                  api_key: data.web.search.searxng.api_key ?? "",
                  timeout_ms: data.web.search.searxng.timeout_ms,
                }
              : undefined,
          },
        },
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载设置失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (isOpen) {
      void load();
    }
  }, [isOpen, load]);

  const backend = form.web?.search?.backend ?? "stub";
  const timeoutMs = form.web?.search?.timeout_ms ?? 15000;
  const searxng = form.web?.search?.searxng ?? {};
  const baseUrl = (searxng.base_url ?? "").trim();
  const saveDisabled = backend === "searxng" && !baseUrl;

  const handleSave = async () => {
    if (saveDisabled) return;
    setSaving(true);
    setError(null);
    setSaveMessage(null);
    try {
      await updateSettings({
        version: form.version,
        web: form.web,
      });
      setSaveMessage("已保存");
      setTimeout(() => setSaveMessage(null), 2000);
    } catch (e) {
      setError(e instanceof Error ? e.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="settings-drawer-overlay" onClick={onClose}>
      <div className="settings-drawer" onClick={(e) => e.stopPropagation()}>
        <div className="settings-drawer-header">
          <h2>Settings</h2>
          <button
            type="button"
            className="settings-drawer-close"
            onClick={onClose}
            aria-label="关闭"
          >
            <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
              <path
                d="M15 5L5 15M5 5l10 10"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
              />
            </svg>
          </button>
        </div>

        <div className="settings-drawer-content">
          {loading && <div className="settings-drawer-loading">加载中…</div>}
          {error && <div className="settings-drawer-error" role="alert">{error}</div>}

          {!loading && (
            <>
              <section className="settings-drawer-section">
                <h3>Web 搜索</h3>
                <div className="settings-drawer-field">
                  <label>搜索后端</label>
                  <div className="settings-drawer-radio-group">
                    {BACKENDS.map((opt) => (
                      <label
                        key={opt.value}
                        className={`settings-drawer-radio-item ${backend === opt.value ? "selected" : ""}`}
                      >
                        <input
                          type="radio"
                          name="backend"
                          checked={backend === opt.value}
                          onChange={() =>
                            setForm((prev) => ({
                              ...prev,
                              web: {
                                ...prev.web,
                                search: {
                                  ...prev.web?.search,
                                  backend: opt.value,
                                  timeout_ms: prev.web?.search?.timeout_ms ?? 15000,
                                  searxng: prev.web?.search?.searxng,
                                },
                              },
                            }))
                          }
                        />
                        <div>
                          <div>{opt.label}</div>
                          <div className="settings-drawer-radio-desc">{opt.desc}</div>
                        </div>
                      </label>
                    ))}
                  </div>
                </div>
                <div className="settings-drawer-field">
                  <label htmlFor="timeout_ms">超时 (ms)</label>
                  <input
                    id="timeout_ms"
                    type="number"
                    className="settings-drawer-input"
                    min={1000}
                    value={timeoutMs}
                    onChange={(e) => {
                      const v = parseInt(e.target.value, 10);
                      if (!Number.isNaN(v))
                        setForm((prev) => ({
                          ...prev,
                          web: {
                            ...prev.web,
                            search: {
                              ...prev.web?.search,
                              timeout_ms: Math.max(1000, v),
                            },
                          },
                        }));
                    }}
                  />
                  <div className="settings-drawer-helper">超时会返回 Timeout</div>
                </div>
                {backend === "searxng" && (
                  <div className="settings-drawer-card">
                    <div className="settings-drawer-field">
                      <label htmlFor="searxng_base_url">SearXNG Base URL（必填）</label>
                      <input
                        id="searxng_base_url"
                        type="url"
                        className="settings-drawer-input"
                        placeholder="http://localhost:8080"
                        value={searxng.base_url ?? ""}
                        onChange={(e) =>
                          setForm((prev) => ({
                            ...prev,
                            web: {
                              ...prev.web,
                              search: {
                                ...prev.web?.search,
                                searxng: {
                                  ...prev.web?.search?.searxng,
                                  base_url: e.target.value,
                                },
                              },
                            },
                          }))
                        }
                      />
                      <div className="settings-drawer-helper">指向 searxng 实例地址</div>
                    </div>
                    <div className="settings-drawer-field">
                      <label htmlFor="searxng_api_key">SearXNG API Key（可选）</label>
                      <input
                        id="searxng_api_key"
                        type={showSearxngPassword ? "text" : "password"}
                        className="settings-drawer-input"
                        value={searxng.api_key ?? ""}
                        onChange={(e) =>
                          setForm((prev) => ({
                            ...prev,
                            web: {
                              ...prev.web,
                              search: {
                                ...prev.web?.search,
                                searxng: {
                                  ...prev.web?.search?.searxng,
                                  api_key: e.target.value,
                                },
                              },
                            },
                          }))
                        }
                      />
                      <label style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 6, fontSize: 13 }}>
                        <input
                          type="checkbox"
                          checked={showSearxngPassword}
                          onChange={(e) => setShowSearxngPassword(e.target.checked)}
                        />
                        显示
                      </label>
                    </div>
                    <div className="settings-drawer-field">
                      <label htmlFor="searxng_timeout_ms">SearXNG 超时 (ms)（可选）</label>
                      <input
                        id="searxng_timeout_ms"
                        type="number"
                        className="settings-drawer-input"
                        min={1000}
                        value={searxng.timeout_ms ?? ""}
                        placeholder={String(timeoutMs)}
                        onChange={(e) => {
                          const v = e.target.value ? parseInt(e.target.value, 10) : undefined;
                          setForm((prev) => ({
                            ...prev,
                            web: {
                              ...prev.web,
                              search: {
                                ...prev.web?.search,
                                searxng: {
                                  ...prev.web?.search?.searxng,
                                  timeout_ms: v !== undefined && !Number.isNaN(v) ? Math.max(1000, v) : undefined,
                                },
                              },
                            },
                          }));
                        }}
                      />
                      <div className="settings-drawer-helper">优先于上方 Web 搜索超时</div>
                    </div>
                  </div>
                )}
                <div className="settings-drawer-hint">
                  新设置只影响后续任务；已创建的 Run 会记录 settings_snapshot 用于回放。
                </div>
              </section>

              <section className="settings-drawer-section">
                <h3>LLM</h3>
                <div className="settings-drawer-coming-soon">Coming soon</div>
              </section>
              <section className="settings-drawer-section">
                <h3>Sandbox</h3>
                <div className="settings-drawer-coming-soon">Coming soon</div>
              </section>
              <section className="settings-drawer-section">
                <h3>Developer</h3>
                <div className="settings-drawer-coming-soon">Coming soon</div>
              </section>
            </>
          )}
        </div>

        <div className="settings-drawer-footer">
          {saveMessage && <span className="settings-drawer-saved-msg">{saveMessage}</span>}
          <button type="button" className="cancel-btn" onClick={onClose}>
            取消
          </button>
          <button
            type="button"
            className="save-btn"
            disabled={saveDisabled || saving}
            onClick={() => void handleSave()}
          >
            {saving ? "保存中…" : "保存"}
          </button>
        </div>
      </div>
    </div>
  );
};
