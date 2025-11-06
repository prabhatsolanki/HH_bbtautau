import os

era = "Run3_2022"
ver = "v2510_v4"
indir = f"/eos/user/p/prsolank/HH_bbtautau_resonant_Run3/merged_hists/{ver}/{era}/"
plotdir = f"/eos/user/p/prsolank/HH_bbtautau_resonant_Run3/merged_hists/{ver}/{era}/plots/"

#varnames = ["tau1_pt", "tau2_pt", "tau1_eta", "tau2_eta", "tautau_m_vis"] #"bbtautau_mass"
varnames = ["tautau_m_vis"] #"bbtautau_mass"

channellist = ["tauTau"]

cat = "inclusive"

using_uncertainties = False #When we turn on Up/Down, the file storage changes due to renameHists.py

for var in varnames:
    for channel in channellist:
        filename = os.path.join(indir, var, f"{var}.root")
        print("Loading fname ", filename)
        os.makedirs(plotdir, exist_ok=True)
        outname = os.path.join(plotdir, f"HHbbtautau_{channel}_{var}_StackPlot.pdf")

        if not using_uncertainties:
            os.system(f"python3 ../FLAF/Analysis/HistPlotter.py --inFile {filename} --bckgConfig ../config/background_samples.yaml --globalConfig ../config/global.yaml --outFile {outname} --var {var} --category {cat} --channel {channel} --uncSource Central --wantData --year {era} --wantQCD True --rebin False --analysis HH_bbtautau --qcdregion OS_Iso --sigConfig ../config/{era}/samples.yaml --wantSignals")

        else:
            filename = os.path.join(indir, var, 'tmp', f"all_histograms_{var}_hadded.root")
            os.system(f"python3 ../FLAF/Analysis/HistPlotter.py --inFile {filename} --bckgConfig ../config/background_samples.yaml --globalConfig ../config/global.yaml --outFile {outname} --var {var} --category {cat} --channel {channel} --uncSource Central --wantData --year {era} --wantQCD True --rebin False --analysis HH_bbtautau --qcdregion SS_AntiIso")
