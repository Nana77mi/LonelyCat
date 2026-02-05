const baseUrl =
  import.meta.env.VITE_CORE_API_URL ||
  import.meta.env.VITE_API_BASE_URL ||
  "/api";

const joinBaseUrl = (base: string, path: string) => {
  if (!base) return path.startsWith("/") ? path : `/${path}`;
  const trimmedBase = base.replace(/\/+$/, "");
  const trimmedPath = path.startsWith("/") ? path : `/${path}`;
  return `${trimmedBase}${trimmedPath}`;
};

const buildUrl = (path: string) => {
  const joined = joinBaseUrl(baseUrl, path);
  const url = new URL(
    joined,
    baseUrl.startsWith("http") ? undefined : window.location.origin
  );
  return url.toString();
};

export type SettingsV0 = {
  version: string;
  web: {
    search: {
      backend: "stub" | "ddg_html" | "baidu_html" | "searxng" | "bocha";
      timeout_ms?: number;
      searxng?: {
        base_url?: string;
        api_key?: string;
        timeout_ms?: number;
      };
    };
    fetch?: {
      fetch_delay_seconds?: number;
    };
    providers?: {
      bocha?: {
        enabled?: boolean;
        api_key?: string;
        base_url?: string;
        timeout_ms?: number;
        top_k_default?: number;
      };
    };
  };
};

export async function fetchSettings(): Promise<SettingsV0> {
  const res = await fetch(buildUrl("/settings"));
  if (!res.ok) {
    throw new Error(`获取设置失败: ${res.status}`);
  }
  return res.json() as Promise<SettingsV0>;
}

export async function updateSettings(
  payload: Partial<SettingsV0>
): Promise<SettingsV0> {
  const res = await fetch(buildUrl("/settings"), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `保存设置失败: ${res.status}`);
  }
  return res.json() as Promise<SettingsV0>;
}
