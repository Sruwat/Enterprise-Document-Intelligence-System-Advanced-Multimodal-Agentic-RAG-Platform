"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

export function RouteTabs({ items }: { items: { href: string; label: string }[] }) {
  const pathname = usePathname();
  return (
    <div className="route-tabs">
      {items.map((item) => <Link key={item.href} className={pathname === item.href ? "active" : ""} href={item.href}>{item.label}</Link>)}
    </div>
  );
}
