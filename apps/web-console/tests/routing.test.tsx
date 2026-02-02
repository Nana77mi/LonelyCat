import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import userEvent from "@testing-library/user-event";
import App from "../src/App";

// Mock fetch globally
const mockFetch = vi.fn();
global.fetch = mockFetch;

describe("Routing", () => {
  beforeEach(() => {
    mockFetch.mockClear();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("should render MemoryPage at /memory route", async () => {
    // Mock memory API responses (facts and proposals)
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ items: [] }),
    });
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ items: [] }),
    });

    render(
      <MemoryRouter initialEntries={["/memory"]}>
        <App />
      </MemoryRouter>
    );

    await waitFor(() => {
      // Check that MemoryPage heading exists (not just the sidebar link)
      const headings = screen.getAllByRole("heading", { name: /Memory/i });
      expect(headings.length).toBeGreaterThan(0);
      // Verify MemoryPage content
      expect(screen.getByText(/Review proposals and manage long-term facts stored for the assistant/i)).toBeInTheDocument();
    });
  });

  it("should show Memory navigation button in Sidebar", async () => {
    render(
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>
    );

    const memoryLink = screen.getByRole("link", { name: /Memory/i });
    expect(memoryLink).toBeInTheDocument();
    expect(memoryLink).toHaveAttribute("href", "/memory");
  });

  it("should navigate to /memory when Memory link is clicked", async () => {
    const user = userEvent.setup();
    // Mock memory API responses for when navigating to /memory
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ items: [] }),
    });
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ items: [] }),
    });

    render(
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>
    );

    const memoryLink = screen.getByRole("link", { name: /Memory/i });
    await user.click(memoryLink);

    await waitFor(() => {
      expect(screen.getByText(/Review proposals and manage long-term facts/i)).toBeInTheDocument();
    });
  });

  it("should highlight Memory link when on /memory route", async () => {
    // Mock memory API responses (facts and proposals)
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ items: [] }),
    });
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ items: [] }),
    });

    render(
      <MemoryRouter initialEntries={["/memory"]}>
        <App />
      </MemoryRouter>
    );

    await waitFor(() => {
      const memoryLink = screen.getByRole("link", { name: /Memory/i });
      expect(memoryLink).toHaveClass("active");
    });
  });

  it("should call memory API when MemoryPage renders", async () => {
    const mockFactsResponse = {
      items: [
        {
          id: "fact-1",
          key: "test.key",
          value: "test value",
          status: "active",
          scope: "global",
          project_id: null,
          session_id: null,
          source_ref: {
            kind: "manual",
            ref_id: "test",
            excerpt: null,
          },
          confidence: 0.9,
          version: 1,
          created_at: "2024-01-01T00:00:00Z",
          updated_at: "2024-01-01T00:00:00Z",
        },
      ],
    };

    const mockProposalsResponse = {
      items: [],
    };

    // Mock fetch for facts
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => mockFactsResponse,
    });

    // Mock fetch for proposals
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => mockProposalsResponse,
    });

    render(
      <MemoryRouter initialEntries={["/memory"]}>
        <App />
      </MemoryRouter>
    );

    await waitFor(() => {
      // Verify fetch was called at least twice (facts and proposals)
      expect(mockFetch).toHaveBeenCalledTimes(2);
      // Verify fetch was called for facts
      const factsCall = mockFetch.mock.calls.find((call) =>
        call[0]?.toString().includes("/memory/facts")
      );
      expect(factsCall).toBeDefined();
      // Verify fetch was called for proposals
      const proposalsCall = mockFetch.mock.calls.find((call) =>
        call[0]?.toString().includes("/memory/proposals")
      );
      expect(proposalsCall).toBeDefined();
    });
  });

  it("should render MemoryPage with facts and proposals", async () => {
    const mockFactsResponse = {
      items: [
        {
          id: "fact-1",
          key: "user.name",
          value: "John Doe",
          status: "active",
          scope: "global",
          project_id: null,
          session_id: null,
          source_ref: {
            kind: "chat",
            ref_id: "conv-1",
            excerpt: "User mentioned their name",
          },
          confidence: 0.95,
          version: 1,
          created_at: "2024-01-01T00:00:00Z",
          updated_at: "2024-01-01T00:00:00Z",
        },
      ],
    };

    const mockProposalsResponse = {
      items: [
        {
          id: "proposal-1",
          payload: {
            key: "user.email",
            value: "john@example.com",
            tags: [],
            ttl_seconds: null,
          },
          status: "pending",
          reason: null,
          confidence: 0.8,
          scope_hint: "global",
          source_ref: {
            kind: "chat",
            ref_id: "conv-1",
            excerpt: "User mentioned their email",
          },
          created_at: "2024-01-01T00:00:00Z",
          updated_at: "2024-01-01T00:00:00Z",
        },
      ],
    };

    // Mock fetch for facts
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => mockFactsResponse,
    });

    // Mock fetch for proposals
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => mockProposalsResponse,
    });

    render(
      <MemoryRouter initialEntries={["/memory"]}>
        <App />
      </MemoryRouter>
    );

    await waitFor(() => {
      // Check facts table - look for table cells
      const factKey = screen.getByText("user.name");
      expect(factKey).toBeInTheDocument();
      expect(screen.getByText("John Doe")).toBeInTheDocument();
      // Check proposals table
      expect(screen.getByText("user.email")).toBeInTheDocument();
      expect(screen.getByText("john@example.com")).toBeInTheDocument();
    }, { timeout: 5000 });
  });
});
