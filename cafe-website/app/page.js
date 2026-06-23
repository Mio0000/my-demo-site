import { getAllCafes } from "../lib/cafes.js";
import CafeGrid from "./CafeGrid.js";

export const metadata = {
  title: "Cafe Demos — Portfolio",
  description: "Professional cafe websites for Melbourne and Hiroshima.",
};

function LeadlightDiamond() {
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
      <rect x="6" y="0" width="8" height="8" transform="rotate(45 6 0)" fill="#D4AF37" fillOpacity="0.8" />
    </svg>
  );
}

export default function HomePage() {
  const cafes = getAllCafes();

  return (
    <div className="min-h-screen bg-cream">

      {/* ── Hero header ── */}
      <header className="relative bg-charcoal py-24 text-center overflow-hidden">
        <div className="leadlight-strip h-1 w-full absolute top-0 left-0 right-0" />

        <div className="absolute inset-x-0 top-0 bottom-0 pointer-events-none">
          <div className="absolute left-8 md:left-20 top-1 bottom-0 w-px bg-gradient-to-b from-brass/0 via-brass/30 to-brass/0" />
          <div className="absolute right-8 md:right-20 top-1 bottom-0 w-px bg-gradient-to-b from-brass/0 via-brass/30 to-brass/0" />
        </div>

        <div className="relative z-10 max-w-2xl mx-auto px-6">
          <p className="font-sans text-xs tracking-[0.25em] uppercase text-brass mb-6">
            Demo Portfolio · Cafe Websites
          </p>
          <h1 className="font-serif text-5xl md:text-7xl text-cream leading-tight mb-4">
            Cafe
            <br />
            <span className="italic text-brass">Demos</span>
          </h1>
          <div className="flex items-center justify-center gap-4 my-6">
            <div className="h-px w-12 bg-brass/60" />
            <LeadlightDiamond />
            <div className="h-px w-12 bg-brass/60" />
          </div>
          <p className="font-sans text-cream/60 leading-relaxed">
            Custom-built demo websites for cafes across Melbourne &amp; Hiroshima.
            <br className="hidden md:block" />
            Click any cafe to explore its full site.
          </p>
        </div>

        <div className="leadlight-strip h-px w-full absolute bottom-0 left-0 right-0" />
      </header>

      <CafeGrid cafes={cafes} />

      <footer className="bg-charcoal py-8 text-center">
        <div className="leadlight-strip h-px w-full mb-6" />
        <p className="font-sans text-xs text-cream/30 tracking-wide">
          Demo Portfolio · {cafes.length} cafes · Melbourne &amp; Hiroshima
        </p>
      </footer>
    </div>
  );
}
