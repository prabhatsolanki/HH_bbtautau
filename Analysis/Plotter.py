import argparse
import os
import hist
import matplotlib.pyplot as plt
import mplhep
import numpy as np
import uproot
import boost_histogram as bh
from matplotlib.ticker import AutoMinorLocator

BACKGROUND_GROUPS = {
    "W + Jets": {"procs": ["WtoLNu"], "label": r"W$\rightarrow \ell\nu$"},
    "Single Higgs": {"procs": ["ggH", "VBFH", "VH", "ttH"], "label": "Single Higgs"},
    "Diboson": {"procs": ["VV", "VVV"], "label": "Diboson"},
    "Single Top": {"procs": ["ST"], "label": "Single Top"},
    "TT": {"procs": ["TT"], "label": r"$t\bar{t}$"},
    "DY": {"procs": ["DY"], "label": r"$Z/\gamma^*\rightarrow \ell\ell$"},
    "QCD": {"procs": ["QCD"], "label": "QCD Multijet"},
}

SIGNAL_GROUPS = {
    "HH": {
        "procs": ["GluGlutoHHto2B2Tau_kl_0p00_kt_1p00_c2_0p00"],
        "label": r"HH ($k_{\lambda}=1$)",
    }
}

DATA_PROCESS = "data"

def _variances_safe(h: hist.Hist) -> np.ndarray:
    v = h.variances()
    return np.zeros_like(h.values()) if v is None else v

def _add_hists(hlist):
    if not hlist:
        raise ValueError("Empty histogram list cannot be summed.")
    out = hlist[0].copy()
    for h in hlist[1:]:
        out += h
    return out

def _build_hist_from_arrays(edges, values, variances):
    hbh = bh.Histogram(bh.axis.Variable(edges), storage=bh.storage.Weight())
    view = hbh.view()
    view.value = np.asarray(values, dtype=float)
    view.variance = np.asarray(variances, dtype=float)
    return hist.Hist(hbh)

def _rebin_constant_factor(h: hist.Hist, factor: int) -> hist.Hist:
    if factor <= 1:
        return h
    values = h.values()
    variances = _variances_safe(h)
    edges = h.axes[0].edges
    n = len(values)
    if n % factor != 0:
        raise ValueError(
            f"Cannot rebin by factor={factor}: number of bins ({n}) is not divisible."
        )
    new_values = values.reshape(-1, factor).sum(axis=1)
    new_variances = variances.reshape(-1, factor).sum(axis=1)
    new_edges = edges[::factor]
    if len(new_edges) != len(new_values) + 1:
        new_edges = np.r_[new_edges, edges[-1]]
    return _build_hist_from_arrays(new_edges, new_values, new_variances)

def _rebin_to_edges(h: hist.Hist, new_edges: np.ndarray) -> hist.Hist:
    new_edges = np.asarray(new_edges, dtype=float)
    old_edges = h.axes[0].edges
    values = h.values()
    variances = _variances_safe(h)

    def _find_edge_index(edge, all_edges, tol=1e-9):
        idx = np.where(np.isclose(all_edges, edge, rtol=0, atol=tol))[0]
        if idx.size == 0:
            raise ValueError(f"Requested rebin edge {edge} not found among original edges.")
        return idx[0]

    new_vals, new_vars = [], []
    for i in range(len(new_edges) - 1):
        left = _find_edge_index(new_edges[i], old_edges)
        right = _find_edge_index(new_edges[i + 1], old_edges)
        if right <= left:
            raise ValueError("New edges are not strictly increasing.")
        new_vals.append(values[left:right].sum())
        new_vars.append(variances[left:right].sum())

    return _build_hist_from_arrays(new_edges, np.asarray(new_vals), np.asarray(new_vars))

def _rebin_hist(h: hist.Hist, rebin_factor: int = 1, rebin_edges=None) -> hist.Hist:
    if rebin_edges:
        return _rebin_to_edges(h, np.asarray(rebin_edges, dtype=float))
    if rebin_factor and rebin_factor > 1:
        return _rebin_constant_factor(h, int(rebin_factor))
    return h

def _to_density(h: hist.Hist) -> hist.Hist:
    edges = h.axes[0].edges
    widths = np.diff(edges)
    vals = h.values()
    vars_ = _variances_safe(h)
    return _build_hist_from_arrays(edges, vals/widths, vars_/(widths**2))

def _format_channel(channel: str) -> str:
    m = channel.lower()
    if "tautau" in m: return r"$\tau_h\tau_h$"
    if "mutau" in m:  return r"$\mu\tau_h$"
    if "etau"  in m:  return r"$e\tau_h$"
    if "mumu"  in m:  return r"$\mu\mu$"
    if "ee"    in m:  return r"$ee$"
    return channel

PALETTES = {
    "Mine":    ["#73A1B2", "#CDBCAB", "#F1BD78", "#A67D44", "#5D1C34","#655C7F","#6E8658"],
}
PALETTE_CHOICES = list(PALETTES.keys())

def _make_palette(name: str, n: int):
    base = PALETTES.get(name, PALETTES["Mine"])
    if len(base) >= n:
        return base[:n]
    reps = (n + len(base) - 1) // len(base)
    return (base * reps)[:n]

def get_histogram(
    file: uproot.ReadOnlyDirectory,
    directory: str,
    process_name: str,
    rebin_factor: int = 1,
    rebin_edges=None,
):
    path = f"{directory}/{process_name}"
    try:
        h_uproot = file[path]
        h = h_uproot.to_hist()
        if len(h.axes) != 1:
            raise ValueError(f"Only 1D hists supported, got {len(h.axes)}D for {path}")
        return _rebin_hist(h, rebin_factor=rebin_factor, rebin_edges=rebin_edges)
    except KeyError:
        return None

def plot_cms_style(
    file_path,
    channel,
    region,
    category,
    output_dir,
    log_scale,
    rebin_factor,
    rebin_edges,
    signal_scale,
    x_label_override, 
    palette_name,
):
    directory_path = f"{channel}/{region}/{category}"
    print(f"--- Generating plot for: {directory_path} ---")

    hists_bkg, hists_sig = {}, {}

    try:
        with uproot.open(file_path) as f:
            get_hist_args = {"rebin_factor": rebin_factor, "rebin_edges": rebin_edges}

            h_data = get_histogram(f, directory_path, DATA_PROCESS, **get_hist_args)
            if h_data is None:
                print(f"Error: Data '{DATA_PROCESS}' not found in '{directory_path}'."); return

            for group, cfg in BACKGROUND_GROUPS.items():
                parts = []
                for proc in cfg["procs"]:
                    h = get_histogram(f, directory_path, proc, **get_hist_args)
                    if h is not None: parts.append(h)
                if parts: hists_bkg[group] = _add_hists(parts)

            for group, cfg in SIGNAL_GROUPS.items():
                parts = []
                for proc in cfg["procs"]:
                    h = get_histogram(f, directory_path, proc, **get_hist_args)
                    if h is not None: parts.append(h)
                if parts: hists_sig[group] = _add_hists(parts)

    except FileNotFoundError:
        print(f"Error: Input file '{file_path}' not found."); return

    if not hists_bkg:
        print("Warning: No background histograms found."); return

    # Sort BG by yield (largest on top)
    bkg_items = list(hists_bkg.items())
    bkg_yields = {name: h.values().sum() for name, h in bkg_items}
    bkg_sorted = sorted(bkg_items, key=lambda kv: bkg_yields[kv[0]])

    # Swap DY and QCD positions in sorted list for better aesthetics
    names = [name for name, _ in bkg_sorted]
    try:
        i_dy = names.index("DY"); i_qcd = names.index("QCD")
        bkg_sorted[i_dy], bkg_sorted[i_qcd] = bkg_sorted[i_qcd], bkg_sorted[i_dy]
    except ValueError:
        pass

    bkg_to_plot = [h for (_, h) in bkg_sorted]
    bkg_labels  = [BACKGROUND_GROUPS[name]["label"] for (name, _) in bkg_sorted]

    n_bkg = len(bkg_to_plot); n_sig = len(hists_sig)
    bkg_colors = _make_palette(palette_name, n_bkg)
    sig_colors = _make_palette(palette_name, max(n_sig, 3))[:n_sig]

    bkg_to_plot_d = [_to_density(h) for h in bkg_to_plot]
    total_bkg = _add_hists(bkg_to_plot) if len(bkg_to_plot) > 1 else bkg_to_plot[0].copy()
    total_bkg_d = _to_density(total_bkg)

    vals_d = total_bkg_d.values()
    unc_d  = np.sqrt(_variances_safe(total_bkg_d))
    edges  = total_bkg_d.axes[0].edges
    centers = (edges[:-1] + edges[1:]) / 2
    widths  = np.diff(edges)
    xerr    = widths / 2.0

    h_data_d = _to_density(h_data)
    data_vals_d = h_data_d.values()
    data_unc_d  = np.sqrt(_variances_safe(h_data_d))

    fig, (ax, rax) = plt.subplots(2, 1, figsize=(11, 11), gridspec_kw={"height_ratios": (3, 1)}, sharex=True)
    for a in (fig, ax, rax): a.set_facecolor("white")
    fig.subplots_adjust(hspace=0.07, left=0.20, right=0.98, bottom=0.09, top=0.95)

    LABEL_FONTSIZE = 22  
    TICK_FONTSIZE  = 18
    LEGEND_FONTSIZE = 17
    CMS_FONTSIZE   = 22
    ANNO_FONTSIZE  = 18

    for a in (ax, rax):
        a.tick_params(axis="both", labelsize=TICK_FONTSIZE, length=7, width=1.6, pad=9)
        a.xaxis.set_minor_locator(AutoMinorLocator()); a.yaxis.set_minor_locator(AutoMinorLocator())
        a.grid(True, which="major", linestyle="-", linewidth=0.7, alpha=0.28)
        a.grid(True, which="minor", linestyle=":", linewidth=0.55, alpha=0.18)

    # Stack
    mplhep.histplot(bkg_to_plot_d, ax=ax, stack=True, histtype="fill", label=bkg_labels, color=bkg_colors)

    # Uncertainty band
    lo = np.r_[vals_d - unc_d, (vals_d - unc_d)[-1]]
    hi = np.r_[vals_d + unc_d, (vals_d + unc_d)[-1]]
    ax.fill_between(edges, lo, hi, step="post", hatch="///", facecolor="none", edgecolor="gray", linewidth=0,
                    label="Stat. Unc.", zorder=2)

    ax.errorbar(
        centers, data_vals_d, yerr=data_unc_d, xerr=xerr,
        fmt="o", color="black", markersize=6, linewidth=1.2,
        label="data obs" 
    )

    # Signals
    for (group, h_sig), col in zip(hists_sig.items(), sig_colors):
        h_sig_scaled_d = _to_density(h_sig * signal_scale)
        sig_label = SIGNAL_GROUPS[group]["label"]
        if not np.isclose(signal_scale, 1.0): sig_label += f" (x{signal_scale:g})"
        mplhep.histplot(h_sig_scaled_d, ax=ax, histtype="step", color=col, label=sig_label, linewidth=2.5)

    if log_scale:
        ax.set_yscale("log")
        pos = vals_d[vals_d > 0]; ymin = max(1e-6, (pos.min()/5.0) if pos.size else 1e-6)
        ax.set_ylim(ymin, ax.get_ylim()[1]*2.0)
    else:
        ax.set_ylim(0.0, max(1.35*(vals_d.max() if vals_d.size else 1.0), 1.0))

    handles, labels = ax.get_legend_handles_labels()
    bkg_pairs = list(zip(bkg_labels, bkg_colors))
    label_to_handle = {lab: h for h, lab in zip(handles, labels)}
    legend_bkgs = [label_to_handle[lab] for lab, _ in reversed(bkg_pairs) if lab in label_to_handle]
    non_bkg = [(lab, label_to_handle[lab]) for lab in labels if lab not in [b for b, _ in bkg_pairs]]
    legend_handles = [h for lab, h in non_bkg] + legend_bkgs
    legend_labels  = [lab for lab, _ in non_bkg] + [lab for lab, _ in reversed(bkg_pairs)]
    ax.legend(legend_handles, legend_labels, loc="upper right", fontsize=LEGEND_FONTSIZE, frameon=False, ncol=2)
    ylab = r"$\frac{\mathrm{Events}}{\mathrm{bin\ width}}\,\left[\frac{1}{\mathrm{GeV}}\right]$"
    ax.set_ylabel(ylab, fontsize=LABEL_FONTSIZE+6, labelpad=14)
    ax.yaxis.set_label_coords(-0.11, 0.83) 
    ax.get_yaxis().get_label().set_verticalalignment("bottom")
    ax.set_xlabel("")
    ax.tick_params(axis="x", labelbottom=False)

    channel_tex = _format_channel(channel)
    ax.text(0.02, 0.98, f"{channel_tex}, {category}",
            transform=ax.transAxes, fontsize=ANNO_FONTSIZE, va="top", ha="left")

    # Ratio 
    mc_mask = vals_d > 0
    mc_vals_safe = np.where(mc_mask, vals_d, 1.0)
    ratio_vals = np.where(mc_mask, data_vals_d / mc_vals_safe, np.nan)
    data_unc_over_mc = np.full_like(ratio_vals, np.nan)
    data_unc_over_mc[mc_mask] = data_unc_d[mc_mask] / mc_vals_safe[mc_mask]

    rax.errorbar(centers, ratio_vals, yerr=data_unc_over_mc, xerr=xerr,
                 fmt="o", color="black", markersize=6, linewidth=1.2)

    ratio_unc_band = np.zeros_like(vals_d); ratio_unc_band[mc_mask] = unc_d[mc_mask] / vals_d[mc_mask]
    rlo = np.r_[1 - ratio_unc_band, (1 - ratio_unc_band)[-1]]
    rhi = np.r_[1 + ratio_unc_band, (1 + ratio_unc_band)[-1]]
    rax.fill_between(edges, rlo, rhi, step="post", hatch="///", facecolor="none", edgecolor="gray", linewidth=0, zorder=2)

    rax.axhline(1.0, ls="--", color="gray"); rax.set_ylim(0.5, 1.5)
    rax.set_ylabel(r"$\mathrm{obs/bkg}$", fontsize=LABEL_FONTSIZE, labelpad=12)
    rax.get_yaxis().get_label().set_verticalalignment("bottom")
    xlabel_tex = r"$m_{\tau\tau}^{\mathrm{vis}}\,[\mathrm{GeV}]$"
    try:
        rax.set_xlabel(xlabel_tex, fontsize=LABEL_FONTSIZE, loc="right")
    except TypeError:
        rax.set_xlabel(xlabel_tex, fontsize=LABEL_FONTSIZE)
        rax.xaxis.set_label_coords(0.995, -0.085)
        rax.get_xaxis().get_label().set_horizontalalignment("right")

    # CMS label
    #mplhep.cms.label(ax=ax, label="Preliminary", data=True, lumi=7.9804, year="", com=13.6, fontsize=CMS_FONTSIZE)
    mplhep.cms.label(ax=ax, label="Preliminary", data=True, lumi=26.6717, year="", com=13.6, fontsize=CMS_FONTSIZE)

    os.makedirs(output_dir, exist_ok=True)
    out = os.path.join(output_dir, f"{channel}_{region}_{category}{'_log' if log_scale else ''}.png")
    print(f"Saving plot to {out}")
    plt.savefig(out, bbox_inches="tight", dpi=150)
    plt.close()


def main():
    parser = argparse.ArgumentParser(description="Generate CMS-style stacked plots for analysis.")
    parser.add_argument("-f", "--file-path", default="tautau_m_vis.root", help="Path to the input ROOT file.")
    parser.add_argument("-c", "--channel", required=True, help="Channel to plot (e.g., tauTau, muTau).")
    parser.add_argument("-r", "--region", required=True, help="Region to use in output filename.")
    parser.add_argument("-g", "--category", default="baseline", help="Category.")
    parser.add_argument("-o", "--output-dir", default="plots", help="Directory to save the plots.")
    parser.add_argument("--log", action="store_true", help="Use logarithmic scale for the y-axis.")
    parser.add_argument("--rebin", type=int, default=1, help="Rebin factor (ignored if --rebin-edges is used).")
    parser.add_argument("--rebin-edges", type=float, nargs="+", default=None, help="New bin edges.")
    parser.add_argument("--signal-scale", type=float, default=1.0, help="Factor to scale the signal histogram by.")
    parser.add_argument("--palette", type=str, default="Mine",
                        choices=PALETTE_CHOICES,
                        help="Color palette to use.")
    parser.add_argument("--xlabel", type=str, default=None, help="(Unused) Kept for compatibility.")
    args = parser.parse_args()

    plot_cms_style(
        file_path=args.file_path,
        channel=args.channel,
        region=args.region,
        category=args.category,
        output_dir=args.output_dir,
        log_scale=args.log,
        rebin_factor=args.rebin,
        rebin_edges=args.rebin_edges,
        signal_scale=args.signal_scale,
        x_label_override=args.xlabel,
        palette_name=args.palette,
    )


if __name__ == "__main__":
    main()