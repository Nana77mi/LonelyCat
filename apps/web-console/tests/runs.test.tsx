import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { RunsPanel } from "../src/components/RunsPanel";
import { createRun, listConversationRuns } from "../src/api/runs";
import type { Run } from "../src/api/runs";

// Mock fetch globally
const mockFetch = vi.fn();
global.fetch = mockFetch;

describe("RunsPanel", () => {
  beforeEach(() => {
    mockFetch.mockClear();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("should render empty state when no runs", () => {
    render(<RunsPanel runs={[]} />);
    expect(screen.getByText("No tasks yet")).toBeInTheDocument();
  });

  it("should render loading state", () => {
    render(<RunsPanel runs={[]} loading={true} />);
    expect(screen.getByText("Loading tasks…")).toBeInTheDocument();
  });

  it("should render error state with retry button", () => {
    const onRetry = vi.fn();
    render(<RunsPanel runs={[]} error="Failed to load" onRetry={onRetry} />);
    expect(screen.getByText("Failed to load tasks")).toBeInTheDocument();
    const retryButton = screen.getByText("重试");
    expect(retryButton).toBeInTheDocument();
    retryButton.click();
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("should render runs list", () => {
    const runs: Run[] = [
      {
        id: "run-1",
        type: "sleep",
        title: "Sleep 5s",
        status: "queued",
        conversation_id: "conv-1",
        input: { seconds: 5 },
        attempt: 0,
        created_at: "2024-01-01T00:00:00Z",
        updated_at: "2024-01-01T00:00:00Z",
      },
      {
        id: "run-2",
        type: "sleep",
        title: null,
        status: "running",
        conversation_id: "conv-1",
        input: { seconds: 10 },
        progress: 50,
        attempt: 0,
        created_at: "2024-01-01T00:01:00Z",
        updated_at: "2024-01-01T00:01:00Z",
      },
      {
        id: "run-3",
        type: "sleep",
        title: "Sleep 3s",
        status: "failed",
        conversation_id: "conv-1",
        input: { seconds: 3 },
        error: "Task failed with error: timeout",
        attempt: 1,
        created_at: "2024-01-01T00:02:00Z",
        updated_at: "2024-01-01T00:02:00Z",
      },
    ];

    render(<RunsPanel runs={runs} />);
    expect(screen.getByText("Sleep 5s")).toBeInTheDocument();
    expect(screen.getByText("sleep")).toBeInTheDocument(); // run-2 没有 title，显示 type
    expect(screen.getByText("Sleep 3s")).toBeInTheDocument();
    expect(screen.getByText("排队中")).toBeInTheDocument();
    expect(screen.getByText("运行中")).toBeInTheDocument();
    expect(screen.getByText("失败")).toBeInTheDocument();
    expect(screen.getByText(/timeout/)).toBeInTheDocument(); // 错误信息
  });

  it("should display progress when available", () => {
    const runs: Run[] = [
      {
        id: "run-1",
        type: "sleep",
        title: "Test",
        status: "running",
        conversation_id: "conv-1",
        input: {},
        progress: 75,
        attempt: 0,
        created_at: "2024-01-01T00:00:00Z",
        updated_at: "2024-01-01T00:00:00Z",
      },
    ];

    render(<RunsPanel runs={runs} />);
    expect(screen.getByText("75%")).toBeInTheDocument();
  });

  it("should call onCreateRun when create button is clicked", () => {
    const onCreateRun = vi.fn();
    render(<RunsPanel runs={[]} onCreateRun={onCreateRun} />);
    const createButton = screen.getByLabelText("创建任务");
    createButton.click();
    expect(onCreateRun).toHaveBeenCalledTimes(1);
  });
});

describe("Runs API", () => {
  beforeEach(() => {
    mockFetch.mockClear();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("should create run successfully", async () => {
    const mockRun: Run = {
      id: "run-1",
      type: "sleep",
      title: "Sleep 5s",
      status: "queued",
      conversation_id: "conv-1",
      input: { seconds: 5 },
      attempt: 0,
      created_at: "2024-01-01T00:00:00Z",
      updated_at: "2024-01-01T00:00:00Z",
    };

    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ run: mockRun }),
    });

    const result = await createRun({
      type: "sleep",
      title: "Sleep 5s",
      conversation_id: "conv-1",
      input: { seconds: 5 },
    });

    expect(result).toEqual(mockRun);
    expect(mockFetch).toHaveBeenCalledTimes(1);
    const call = mockFetch.mock.calls[0];
    expect(call[0]).toContain("/runs");
    expect(call[1]?.method).toBe("POST");
  });

  it("should list conversation runs", async () => {
    const mockRuns: Run[] = [
      {
        id: "run-1",
        type: "sleep",
        title: "Sleep 5s",
        status: "queued",
        conversation_id: "conv-1",
        input: { seconds: 5 },
        attempt: 0,
        created_at: "2024-01-01T00:00:00Z",
        updated_at: "2024-01-01T00:00:00Z",
      },
    ];

    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ items: mockRuns }),
    });

    const result = await listConversationRuns("conv-1");

    expect(result).toEqual(mockRuns);
    expect(mockFetch).toHaveBeenCalledTimes(1);
    const call = mockFetch.mock.calls[0];
    expect(call[0]).toContain("/conversations/conv-1/runs");
  });

  it("should handle polling - status changes from running to succeeded", async () => {
    const runningRun: Run = {
      id: "run-1",
      type: "sleep",
      title: "Sleep 5s",
      status: "running",
      conversation_id: "conv-1",
      input: { seconds: 5 },
      attempt: 0,
      created_at: "2024-01-01T00:00:00Z",
      updated_at: "2024-01-01T00:01:00Z",
    };

    const succeededRun: Run = {
      id: "run-1",
      type: "sleep",
      title: "Sleep 5s",
      status: "succeeded",
      conversation_id: "conv-1",
      input: { seconds: 5 },
      output: { result: "completed" },
      attempt: 0,
      created_at: "2024-01-01T00:00:00Z",
      updated_at: "2024-01-01T00:02:00Z",
    };

    // First call returns running
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ items: [runningRun] }),
    });

    const firstResult = await listConversationRuns("conv-1");
    expect(firstResult[0].status).toBe("running");

    // Second call returns succeeded
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ items: [succeededRun] }),
    });

    const secondResult = await listConversationRuns("conv-1");
    expect(secondResult[0].status).toBe("succeeded");
    expect(secondResult[0].output).toEqual({ result: "completed" });
  });
});
