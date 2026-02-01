import { MemoryPage } from "./pages/MemoryPage";

const App = () => {
  const currentPath = typeof window === "undefined" ? "/" : window.location.pathname;
  const isMemory = currentPath === "/memory";

  return (
    <main>
      <h1>LonelyCat Console</h1>
      <nav>
        <a href="/">Home</a>
        {" | "}
        <a href="/memory">Memory</a>
      </nav>
      {isMemory ? (
        <MemoryPage />
      ) : (
        <section>
          <p>Use the navigation to explore the console.</p>
        </section>
      )}
    </main>
  );
};

export default App;
