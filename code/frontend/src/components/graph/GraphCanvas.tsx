import { useEffect, useRef } from "react";
import * as d3 from "d3";
import { classHex } from "../../lib/utils";
import type { GraphEdge, GraphNode } from "../../types";

// ─── GraphCanvas ─────────────────────────────────────────────────────────────

interface GraphCanvasProps {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

interface SimNode extends GraphNode, d3.SimulationNodeDatum {
  x?: number;
  y?: number;
}

interface SimLink extends d3.SimulationLinkDatum<SimNode> {
  predicate: string;
}

export function GraphCanvas({ nodes, edges }: GraphCanvasProps) {
  const svgRef = useRef<SVGSVGElement>(null);

  useEffect(() => {
    if (!svgRef.current || nodes.length === 0) return;
    const svg = d3.select(svgRef.current);
    svg.selectAll("*").remove();

    const W = svgRef.current.clientWidth;
    const H = svgRef.current.clientHeight;

    // Build an id → index map for D3 links
    const nodeById = new Map(nodes.map((n) => [n.id, n]));

    const simNodes: SimNode[] = nodes.map((n) => ({ ...n }));
    const simLinks: SimLink[] = edges
      .filter((e) => nodeById.has(e.source) && nodeById.has(e.target))
      .map((e) => ({ source: e.source, target: e.target, predicate: e.predicate }));

    // Arrow marker
    svg
      .append("defs")
      .append("marker")
      .attr("id", "arrow")
      .attr("viewBox", "0 0 10 10")
      .attr("refX", 18)
      .attr("refY", 5)
      .attr("markerWidth", 6)
      .attr("markerHeight", 6)
      .attr("orient", "auto-start-reverse")
      .append("path")
      .attr("d", "M2 1L8 5L2 9")
      .attr("fill", "none")
      .attr("stroke", "#a1a1aa")
      .attr("stroke-width", 1.5);

    const g = svg.append("g");

    // Zoom
    svg.call(
      d3.zoom<SVGSVGElement, unknown>().on("zoom", (e) =>
        g.attr("transform", e.transform.toString())
      )
    );

    const sim = d3
      .forceSimulation<SimNode>(simNodes)
      .force("link", d3.forceLink<SimNode, SimLink>(simLinks).id((d) => d.id).distance(80))
      .force("charge", d3.forceManyBody().strength(-120))
      .force("center", d3.forceCenter(W / 2, H / 2))
      .force("collision", d3.forceCollide(24));

    // Edges
    const link = g
      .append("g")
      .selectAll("line")
      .data(simLinks)
      .join("line")
      .attr("stroke", "#d4d4d8")
      .attr("stroke-width", 1)
      .attr("marker-end", "url(#arrow)");

    // Edge labels (shown only on hover via title)
    link.append("title").text((d) => d.predicate);

    // Nodes
    const node = g
      .append("g")
      .selectAll<SVGGElement, SimNode>("g")
      .data(simNodes)
      .join("g")
      .attr("cursor", "pointer")
      .call(
        d3
          .drag<SVGGElement, SimNode>()
          .on("start", (e, d) => { if (!e.active) sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
          .on("drag",  (e, d) => { d.fx = e.x; d.fy = e.y; })
          .on("end",   (e, d) => { if (!e.active) sim.alphaTarget(0); d.fx = null; d.fy = null; })
      );

    node
      .append("circle")
      .attr("r", 10)
      .attr("fill", (d) => classHex(d.labels[0] ?? "unknown"))
      .attr("stroke", "#fff")
      .attr("stroke-width", 1.5);

    node
      .append("text")
      .text((d) => d.name.length > 14 ? d.name.slice(0, 12) + "…" : d.name)
      .attr("dy", 22)
      .attr("text-anchor", "middle")
      .attr("font-size", 9)
      .attr("fill", "#71717a");

    node.append("title").text((d) => `${d.labels[0]}: ${d.name}`);

    sim.on("tick", () => {
      link
        .attr("x1", (d) => (d.source as SimNode).x ?? 0)
        .attr("y1", (d) => (d.source as SimNode).y ?? 0)
        .attr("x2", (d) => (d.target as SimNode).x ?? 0)
        .attr("y2", (d) => (d.target as SimNode).y ?? 0);
      node.attr("transform", (d) => `translate(${d.x ?? 0},${d.y ?? 0})`);
    });

    return () => { sim.stop(); };
  }, [nodes, edges]);

  if (nodes.length === 0) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-zinc-400">
        No graph data — run extraction first
      </div>
    );
  }

  return <svg ref={svgRef} className="h-full w-full" />;
}

