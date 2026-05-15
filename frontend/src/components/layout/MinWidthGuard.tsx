import { useEffect, useState } from "react";

/** Çok dar pencerelerde düzen bozulmasını önlemek için yumuşak alt sınır (1280 hedefinin altı). */
const MIN_WIDTH = 1024;

export default function MinWidthGuard({ children }: { children: React.ReactNode }) {
  const [width, setWidth] = useState(typeof window !== "undefined" ? window.innerWidth : MIN_WIDTH);

  useEffect(() => {
    const check = () => setWidth(window.innerWidth);
    check();
    window.addEventListener("resize", check);
    return () => window.removeEventListener("resize", check);
  }, []);

  if (width >= MIN_WIDTH) return <>{children}</>;

  return (
    <div className="flex min-h-screen w-full min-w-0 flex-col items-center justify-center bg-slate-100 p-8">
      <div className="max-w-md rounded-2xl border border-slate-200 bg-white p-8 text-center shadow-xl">
        <div className="mb-4 text-5xl" aria-hidden>
          🖥️
        </div>
        <h1 className="mb-2 text-xl font-semibold text-slate-800">Ekran çözünürlüğü yetersiz</h1>
        <p className="mb-6 text-slate-600">
          TestQube düzenleyici bu görünüm için en az <strong className="text-slate-800">{MIN_WIDTH}px</strong> genişlik
          önerir. Lütfen pencereyi büyütün veya tam ekran kullanın.
        </p>
        <p className="text-sm text-slate-500">
          Mevcut genişlik: <strong>{width}px</strong>
        </p>
      </div>
    </div>
  );
}
