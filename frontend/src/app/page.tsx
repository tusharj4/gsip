import Link from "next/link";

const features = [
  {
    title: "Conflict Detection",
    description: "Draw a corridor and detect intersections with forests, CRZ, wildlife sanctuaries, and 1,500+ layers in under 3 seconds.",
    href: "/map",
    icon: "⚠️",
    color: "bg-red-50 border-red-200",
  },
  {
    title: "Gap Analysis",
    description: "Identify under-served areas for hospitals, schools, and anganwadis using population data.",
    href: "/analysis",
    icon: "📊",
    color: "bg-blue-50 border-blue-200",
  },
  {
    title: "Route Optimization",
    description: "Score alternative alignments on forest overlap, settlement proximity, and cost.",
    href: "/map",
    icon: "🗺️",
    color: "bg-green-50 border-green-200",
  },
  {
    title: "Pre-Alignment Reports",
    description: "Generate PDF reports with conflict tables, regulatory clearances, and corridor maps.",
    href: "/reports",
    icon: "📄",
    color: "bg-purple-50 border-purple-200",
  },
];

export default function Home() {
  return (
    <div className="min-h-screen flex flex-col">
      {/* Header */}
      <header className="bg-brand-700 text-white px-6 py-4 flex items-center justify-between shadow-lg">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">
            PM GatiShakti Intelligence Platform
          </h1>
          <p className="text-brand-100 text-sm mt-0.5">
            Open-source geospatial decision support for infrastructure planning
          </p>
        </div>
        <nav className="flex gap-4 text-sm font-medium">
          <Link href="/map" className="hover:text-brand-100 transition-colors">Map</Link>
          <Link href="/projects" className="hover:text-brand-100 transition-colors">Projects</Link>
          <Link href="/analysis" className="hover:text-brand-100 transition-colors">Analysis</Link>
          <Link href="/reports" className="hover:text-brand-100 transition-colors">Reports</Link>
        </nav>
      </header>

      {/* Hero */}
      <main className="flex-1 px-6 py-12 max-w-6xl mx-auto w-full">
        <div className="text-center mb-12">
          <h2 className="text-4xl font-bold text-brand-700 mb-4">
            Smarter Infrastructure Planning
          </h2>
          <p className="text-xl text-gray-600 max-w-3xl mx-auto">
            Detect conflicts, identify gaps, and optimize alignments using 1,500+ GIS layers —
            all powered by open-source technology and no proprietary APIs.
          </p>
          <div className="mt-8 flex gap-4 justify-center">
            <Link
              href="/map"
              className="bg-brand-500 hover:bg-brand-700 text-white font-semibold px-8 py-3 rounded-lg transition-colors"
            >
              Open Map
            </Link>
            <Link
              href="/projects"
              className="border border-brand-500 text-brand-500 hover:bg-brand-50 font-semibold px-8 py-3 rounded-lg transition-colors"
            >
              View Projects
            </Link>
          </div>
        </div>

        {/* Feature cards */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {features.map((f) => (
            <Link
              key={f.title}
              href={f.href}
              className={`block p-6 rounded-xl border-2 ${f.color} hover:shadow-md transition-shadow`}
            >
              <div className="text-3xl mb-3">{f.icon}</div>
              <h3 className="text-lg font-semibold text-brand-700 mb-2">{f.title}</h3>
              <p className="text-gray-600 text-sm">{f.description}</p>
            </Link>
          ))}
        </div>

        {/* Stack badge */}
        <div className="mt-12 text-center">
          <p className="text-sm text-gray-500">
            Built with{" "}
            <span className="font-medium">MapLibre GL</span> ·{" "}
            <span className="font-medium">PostGIS</span> ·{" "}
            <span className="font-medium">FastAPI</span> ·{" "}
            <span className="font-medium">OpenFreeMap</span> ·{" "}
            <span className="font-medium">Claude API</span>
            {" "}— 100% free &amp; open-source
          </p>
        </div>
      </main>
    </div>
  );
}
