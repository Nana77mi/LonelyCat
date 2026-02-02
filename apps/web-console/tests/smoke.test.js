import { readFile } from "node:fs/promises";
import { test } from "node:test";
import assert from "node:assert/strict";
import path from "node:path";

const appPath = path.join(process.cwd(), "src", "App.tsx");

test("web console shell includes main App component", async () => {
  const content = await readFile(appPath, "utf-8");
  assert.match(content, /export default App/);
  assert.match(content, /const App/);
});
