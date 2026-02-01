import { readFile } from "node:fs/promises";
import { test } from "node:test";
import assert from "node:assert/strict";
import path from "node:path";

const appPath = path.join(process.cwd(), "src", "App.tsx");
const apiPath = path.join(process.cwd(), "src", "api", "memory.ts");
const drawerPath = path.join(process.cwd(), "src", "components", "FactDetailsDrawer.tsx");

test("memory route and page are wired in", async () => {
  const content = await readFile(appPath, "utf-8");
  assert.match(content, /\/memory/);
  assert.match(content, /MemoryPage/);
});

test("memory api helpers are defined", async () => {
  const content = await readFile(apiPath, "utf-8");
  assert.match(content, /export const fetchFacts/);
  assert.match(content, /export const proposeFact/);
  assert.match(content, /export const retractFact/);
  assert.match(content, /export const fetchFactChain/);
});

test("fact details drawer component exists", async () => {
  const content = await readFile(drawerPath, "utf-8");
  assert.match(content, /FactDetailsDrawer/);
});
