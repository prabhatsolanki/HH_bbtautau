import importlib
from FLAF.Common.Utilities import *
from FLAF.Common.HistHelper import *

if __name__ == "__main__":
    sys.path.append(os.environ["ANALYSIS_PATH"])

initialized = False
analysis = None


def Initialize():
    global initialized
    if not initialized:
        headers_dir = os.path.dirname(os.path.abspath(__file__))
        ROOT.gROOT.ProcessLine(f".include {os.environ['ANALYSIS_PATH']}")
        ROOT.gInterpreter.Declare(f'#include "FLAF/include/HistHelper.h"')
        ROOT.gInterpreter.Declare(f'#include "FLAF/include/Utilities.h"')
        ROOT.gROOT.ProcessLine(f'#include "FLAF/include/MT2.h"')
        ROOT.gROOT.ProcessLine(f'#include "FLAF/include/Lester_mt2_bisect.cpp"')
        ROOT.gROOT.ProcessLine('#include "FLAF/include/AnalysisTools.h"')
        ROOT.gROOT.ProcessLine('#include "FLAF/include/AnalysisMath.h"')
        initialized = True


def analysis_setup(setup):
    global analysis
    analysis_import = setup.global_params["analysis_import"]
    analysis = importlib.import_module(f"{analysis_import}")


def GetDfw(
    df,
    df_caches,
    global_params,
    shift="Central",
    col_names_central=[],
    col_types_central=[],
    cache_map_name="cache_map_Central",
):
    period = global_params["era"]
    kwargset = (
        {}
    )  # here go the customisations for each analysis eventually extrcting stuff from the global params
    # Example from Hmm analysis:

    kwargset["isData"] = global_params["process_group"] == "data"
    kwargset["wantTriggerSFErrors"] = global_params["compute_rel_weights"]
    kwargset["wantScales"] = global_params["compute_unc_variations"]
    kwargset["colToSave"] = []
    kwargset["deepTauVersion"] = global_params["deepTauVersion"]
    kwargset["bTagWPString"] = "Medium"
    kwargset["pNetWPstring"] = "Loose"
    kwargset["region"] = global_params["region"]
    kwargset["isCentral"] = True
    datasetType = 3
    if global_params["process_name"] == "TT":
        datasetType = 1
    if global_params["process_name"] == "DY":
        datasetType = 2
    kwargset["whichType"] = datasetType
    kwargset["run_ffs"] = global_params.get("run_ffs", False)
    dfw = analysis.DataFrameBuilderForHistograms(df, global_params, period, **kwargset)

    if df_caches:
        for df_cache in df_caches:
            dfWrapped_cache = analysis.DataFrameBuilderForHistograms(
                df_cache, global_params, period, **kwargset
            )
            AddCacheColumnsInDf(dfw, dfWrapped_cache, cache_map_name)

    if shift == "Valid" and global_params["compute_unc_variations"]:
        dfw.CreateFromDelta(col_names_central, col_types_central)
    if shift != "Central" and global_params["compute_unc_variations"]:
        dfw.AddMissingColumns(col_names_central, col_types_central)
    new_dfw = analysis.PrepareDfForHistograms(dfw)
    return new_dfw


def DefineWeightForHistograms(
    dfw,
    uncName,
    uncScale,
    unc_cfg_dict,
    hist_cfg_dict,
    global_params,
    final_weight_name="weight_for_hists",
):
    categories = global_params["categories"]
    boosted_categories = global_params.get("boosted_categories", [])
    process_group = global_params["process_group"]
    isCentral = uncName == "Central"
    total_weight_expression = (
        # channel, cat, boosted_categories --> these are not needed in the GetWeight function therefore I just put some placeholders
        analysis.GetWeight(global_params["channels_to_consider"])
        if process_group != "data"
        else "1"
    )  # are we sure?
    weight_name = "final_weight"
    if weight_name not in dfw.df.GetColumnNames():
        dfw.df = dfw.df.Define(weight_name, total_weight_expression)
    if not isCentral and type(unc_cfg_dict) == dict:
        if (
            uncName in unc_cfg_dict.keys()
            and "expression" in unc_cfg_dict[uncName].keys()
        ):
            weight_name = unc_cfg_dict[uncName]["expression"].format(scale=uncScale)
    dfw.df = dfw.df.Define(final_weight_name, weight_name)

    # fake-factor “shape” weight, only for central
    if isCentral:
        cols = set(map(str, dfw.df.GetColumnNames()))
        if "ff_comb_weight" in cols:
            if process_group == "data":
                # data: the ML weight is just the FF comb weight
                dfw.df = dfw.df.Define("weight_MLshape_Central", "ff_comb_weight")
            else:
                # MC: multiply the already defined final_weight by the FF comb weight
                dfw.df = dfw.df.Define("weight_MLshape_Central", "final_weight * ff_comb_weight")
            dfw.colToSave.append("weight_MLshape_Central")