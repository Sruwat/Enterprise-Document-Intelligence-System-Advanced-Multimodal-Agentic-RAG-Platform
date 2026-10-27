import Link from "next/link";
import { ArrowRight, Database, Menu, Sparkles } from "lucide-react";

export function PublicSiteShell({ children, active }: { children: React.ReactNode; active?: "features" | "usage" }) {
  return <main className="public-site">
    <header className="public-nav">
      <Link className="public-brand" href="/"><span className="public-brand-mark"><Sparkles size={18} /></span><span><strong>Aiwana</strong><small>Private document intelligence</small></span></Link>
      <nav className="public-links" aria-label="Product"><Link className={active === "features" ? "active" : ""} href="/features">Features</Link><Link className={active === "usage" ? "active" : ""} href="/usage">Use cases</Link><Link href="/#captivedata">Captive Data</Link></nav>
      <div className="public-actions"><Link className="public-text-link" href="/">Open workspace</Link><Link className="public-cta" href="/">Try Aiwana <ArrowRight size={16} /></Link><button className="public-menu" aria-label="Open product navigation"><Menu size={18} /></button></div>
    </header>
    {children}
    <footer className="public-footer"><div className="public-footer-brand"><span className="public-brand-mark"><Database size={17} /></span><strong>Aiwana</strong></div><span>Private intelligence for documents your business cannot afford to lose.</span><div className="public-footer-links"><Link href="/features">Features</Link><Link href="/usage">Use cases</Link><Link href="/data-vault">Data Vault</Link></div></footer>
  </main>;
}

export function ProductPill({ children }: { children: React.ReactNode }) { return <span className="product-pill"><span className="pulse-dot" />{children}</span>; }
