// Pyodide Bridge — loads the frozen Wood Shake engine into Pyodide and exposes
// browser-side async functions mirroring the old local-server endpoints.
// Serve over HTTP (not file://); browsers block fetch() of adjacent local files otherwise.

const PYODIDE_INDEX_URL = "https://cdn.jsdelivr.net/pyodide/v0.28.0/full/";
const PYODIDE_SCRIPT_URL = `${PYODIDE_INDEX_URL}pyodide.js`;

const ENGINE_FILES = [
  "candidate_display.py",
  "candidate_emitters.py",
  "candidate_model.py",
  "confirmation_builder.py",
  "eagleview_geometry_parser.py",
  "facet_basis.py",
  "geometry_core.py",
  "module1_m2interface.py",
  "module1_selected_valley_handoff.py",
  "module1_service.py",
  "module1_yager_proof.py",
  "module2_assembly.py",
  "module2_scope_expansion.py",
  "notch_candidate_emitter.py",
  "regression_test.py",
  "transition_enumerator.py",
  "transition_events.py",
  "workbench_diagram_data.py",
  "workbench_roof_layout.py",
  "workbench_seam.py",
  // Carrier / comparison engine (Build A — page 3 live comparison). Additive load only;
  // these files are byte-identical to the frozen engine.
  "shared_category_registry.py",
  "module3_keying.py",
  "operation_dimension.py",
  "module3_comparison_oracle.py",
  "comparison_caller.py",
  "carrier_parser.py",          // v60: manual_carrier_entry imports consolidate_RR from here.
                                //      MUST load BEFORE manual_carrier_entry or the report dies with
                                //      ModuleNotFoundError at module-load time. Its only dependency is
                                //      shared_category_registry, already loaded above.
  "manual_carrier_entry.py",
  // Module 3 report engine (page 4). Additive load only; byte-identical to the frozen engine.
  "scope_argument_builder.py",
  "argument_caller.py",
  "repair_logic_library.py",
  "module3_render_engine.py",
  "module3_report_renderer.py",
  "module3_language_guard.py",
  "module3_caller.py",
  "category_display_names.py",
  "report_diagram_svg.py",
  // Layer A: raw carrier-estimate text -> structured header + line items (page 3 prefill).
  "carrier_layer_a.py",
  "XML.txt",
];

let pyodideInstance = null;
let readyPromise = null;

function loadScript(src) {
  return new Promise((resolve, reject) => {
    if (globalThis.loadPyodide) { resolve(); return; }
    const script = document.createElement("script");
    script.src = src; script.async = true;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error(`Failed to load ${src}`));
    document.head.appendChild(script);
  });
}

async function fetchText(path) {
  const response = await fetch(path, { cache: "no-store" });
  if (!response.ok) throw new Error(`Failed to fetch ${path}: HTTP ${response.status}`);
  return response.text();
}

async function loadEngineFiles(pyodide) {
  for (const filename of ENGINE_FILES) {
    const text = await fetchText(filename);
    pyodide.FS.writeFile(filename, text);
  }
}

async function initializePythonHelpers(pyodide) {
  await pyodide.runPythonAsync(`
import json
from dataclasses import asdict, is_dataclass


def _wb_to_plain(obj):
    if is_dataclass(obj):
        return _wb_to_plain(asdict(obj))
    if isinstance(obj, dict):
        return {str(k): _wb_to_plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_wb_to_plain(v) for v in obj]
    if hasattr(obj, "tolist"):
        return obj.tolist()
    return obj


def _wb_shake_ea(scope_result):
    # total_EA = the SHAKE_FIELD_RR line ONLY (never sum other EA-unit lines like CHIMNEY_FLASH)
    for line in scope_result.aggregated_scope:
        if line.category_id == "SHAKE_FIELD_RR":
            try:
                v = float(line.qty)
                return int(v) if v.is_integer() else v
            except (TypeError, ValueError):
                return 0
    return 0


def _wb_scope_summary(scope_result):
    plain = _wb_to_plain(scope_result)
    plain["total_EA"] = _wb_shake_ea(scope_result)
    plain["total_SF"] = plain.get("affected_SF_display_total")
    plain["valley_LF"] = plain.get("selected_valley_LF_total")
    # Each ridge's CONTACTED length — the run the repair actually touches. It bounds the vent (you
    # cannot replace more vent than the ridge you are working on), and a ridge with ZERO contact is
    # not in the repair at all and cannot be marked vented. It depends on the user's SELECTION, not
    # on the geometry, so it can only come from the compute.
    plain["ridge_contacts"] = {
        str(c.line_id): round(float(c.contact_LF), 2)
        for c in getattr(scope_result, "deduped_edges", ()) or ()
        if c.edge_type == "RIDGE"
    }
    return plain
`);
}

async function boot() {
  await loadScript(PYODIDE_SCRIPT_URL);
  const pyodide = await globalThis.loadPyodide({ indexURL: PYODIDE_INDEX_URL });
  await pyodide.loadPackage(["numpy", "matplotlib"]);
  await loadEngineFiles(pyodide);
  await initializePythonHelpers(pyodide);
  pyodideInstance = pyodide;
  return pyodide;
}

export function ready() {
  if (!readyPromise) readyPromise = boot();
  return readyPromise;
}

async function runJson(pythonSource, globals = {}) {
  const pyodide = await ready();
  for (const [name, value] of Object.entries(globals)) pyodide.globals.set(name, value);
  try {
    const jsonText = await pyodide.runPythonAsync(pythonSource);
    return JSON.parse(jsonText);
  } finally {
    for (const name of Object.keys(globals)) {
      try { pyodide.globals.delete(name); } catch (_e) {}
    }
  }
}

export async function bundledXmlText() {
  await ready();
  return runJson(`
import json
json.dumps(open("XML.txt", "r", encoding="utf-8").read())
`);
}

export async function roofLayout(xmlText) {
  return runJson(`
import json
from workbench_roof_layout import build_roof_layout
json.dumps(build_roof_layout(xml_text))
`, { xml_text: xmlText });
}

export async function scopeFromSelection(xmlText, uiSelection) {
  return runJson(`
import json
from workbench_seam import build_scope_from_ui_selection
ui_selection = json.loads(ui_selection_json)
result = build_scope_from_ui_selection(xml_text, ui_selection)
json.dumps(_wb_scope_summary(result))
`, { xml_text: xmlText, ui_selection_json: JSON.stringify(uiSelection || {}) });
}

export async function diagramData(xmlText, uiSelection) {
  return runJson(`
import json
from workbench_diagram_data import build_diagram_data
ui_selection = json.loads(ui_selection_json)
json.dumps(build_diagram_data(xml_text, ui_selection))
`, { xml_text: xmlText, ui_selection_json: JSON.stringify(uiSelection || {}) });
}

export async function workbenchUpdate(xmlText, uiSelection = {}) {
  return runJson(`
import json
from workbench_seam import build_scope_from_ui_selection
from workbench_diagram_data import build_diagram_data
ui_selection = json.loads(ui_selection_json)
scope = build_scope_from_ui_selection(xml_text, ui_selection)
diagram = build_diagram_data(xml_text, ui_selection)
# ONE SERIALISER, USED EVERYWHERE. This function used to hand-build a SECOND, divergent scope dict
# with only three keys - so ridge_contacts (which _wb_scope_summary builds correctly) never reached
# the UI, every ridge read a contact of 0, and the "this ridge is not in the repair" guard fired on
# every ridge. THE DATA WAS ALWAYS THERE; the bridge simply never shipped it on the path page 2 uses.
#
# This is the THIRD time a duplicated serialisation path has silently dropped a field (v42: the
# diagram path dropped transition_repairs; the same build: total_SF came from a stale source). The
# duplicate is deleted rather than patched: workbenchUpdate now returns the canonical summary, so a
# field added to _wb_scope_summary is automatically available to every caller. A regression locks
# field parity so the two can never diverge again.
json.dumps({
    "scope": _wb_scope_summary(scope),
    "diagram": diagram,
})
`, { xml_text: xmlText, ui_selection_json: JSON.stringify(uiSelection || {}) });
}

export async function yagerUiSelection(xmlText) {
  return runJson(`
import json
from module1_yager_proof import YAGER_CONFIRMED_SELECTION
from workbench_seam import _ui_selection_from_confirmed_selection
selection = _ui_selection_from_confirmed_selection(YAGER_CONFIRMED_SELECTION, xml_text=xml_text)
json.dumps(selection)
`, { xml_text: xmlText });
}

export async function yagerScope(xmlText) {
  const uiSelection = await yagerUiSelection(xmlText);
  return scopeFromSelection(xmlText, uiSelection);
}

// --- Build A: carrier / comparison engine (page 3) -------------------------
// requiredScope: the confirmed-selection scope (same call page 2 uses), so page 3
// can display and verify the required numbers reproduce page 2's.
// transitionStates: which detected transitions are ACTIVE and by which path — PATH_A (auto,
// swept >=95%), PATH_B (user-asserted), or BOTH. The ENGINE decides; the UI only draws it.
export async function transitionStates(xmlText, uiSelection) {
  return runJson(`
import json
from workbench_seam import transition_states
json.dumps(_wb_to_plain(transition_states(xml_text, json.loads(ui_selection_json))))
`, { xml_text: xmlText, ui_selection_json: JSON.stringify(uiSelection || {}) });
}

export async function requiredScope(xmlText, uiSelection) {
  return scopeFromSelection(xmlText, uiSelection);
}

// buildCarrierSummary: carrier_scope_summary from confirmed manual-entry rows.
export async function buildCarrierSummary(rows) {
  return runJson(`
import json
from manual_carrier_entry import build_carrier_summary_from_manual_entry
rows = json.loads(rows_json)
summary = build_carrier_summary_from_manual_entry(rows)
json.dumps(_wb_to_plain(summary))
`, { rows_json: JSON.stringify(rows || []) });
}

// buildScopeComparison: the real comparison. module2_result is a Python object that
// cannot cross the JS boundary, so assemble -> carrier-summary -> compare all run in
// one Python execution from (xmlText, uiSelection, carrierRows). Returns the status,
// required totals (for page-2 verification), and the scope_comparison lines page 3 renders.
export async function buildScopeComparison(xmlText, uiSelection, carrierRows) {
  return runJson(`
import json
from workbench_seam import build_scope_from_ui_selection
from manual_carrier_entry import build_carrier_summary_from_manual_entry
from comparison_caller import build_scope_comparison

ui_selection = json.loads(ui_selection_json)
rows = json.loads(rows_json)
module2_result = build_scope_from_ui_selection(xml_text, ui_selection)
carrier_summary = build_carrier_summary_from_manual_entry(rows) if rows else None
result = build_scope_comparison(module2_result, carrier_summary)

req = result.get("required") or {}
out = {
    "status": result["status"],
    "required_totals": _wb_to_plain(result.get("required_totals")),
    "required_shake": _wb_to_plain(req.get("SHAKE_FIELD_RR")),
    "carrier_parser_status": (carrier_summary or {}).get("parser_status"),
    "duplicate_comparison_categories": list((carrier_summary or {}).get("duplicate_comparison_categories", []) or []),
    "scope_comparison": _wb_to_plain(result.get("scope_comparison")),
}
json.dumps(out)
`, { xml_text: xmlText, ui_selection_json: JSON.stringify(uiSelection || {}), rows_json: JSON.stringify(carrierRows || []) });
}

// buildModule3Report: the FULL Module 3 report pipeline in ONE Python execution.
// module2_result / carrier_summary are Python objects that cannot cross the JS boundary, so
// assemble -> carrier-summary -> comparison -> argument -> module3 inputs -> render -> to_html
// all run server-side here. Nothing is reimplemented in JS; page 4 only displays the HTML.
// carrierRows == null/[] -> REQUIRED_SCOPE_ONLY mode (no carrier estimate was provided).
export async function buildModule3Report(xmlText, uiSelection, carrierRows, vci, opts = {}) {
  // Report branding is PER-DEVICE, not per-claim: the logo + "Prepared by" text are stored in
  // localStorage on page 1 (deliberately separate from the sessionStorage claim state, so a claim
  // reset never wipes them). Read them here and carry them to the renderer as a base64 data URI +
  // free text. Absent -> the header degrades to the plain title + attribution line.
  let brandLogo = "", brandPreparedBy = "";
  try { brandLogo = localStorage.getItem("woodShakeBranding.logoDataUri") || ""; } catch (e) {}
  try { brandPreparedBy = localStorage.getItem("woodShakeBranding.preparedBy") || ""; } catch (e) {}
  return runJson(`
import json
from workbench_seam import build_scope_from_ui_selection
from manual_carrier_entry import build_carrier_summary_from_manual_entry
from comparison_caller import build_scope_comparison
from argument_caller import build_scope_argument
from module3_caller import build_module3_inputs, render_module3_report
from module3_language_guard import safe_export
from workbench_roof_layout import build_roof_layout
from workbench_diagram_data import build_diagram_data
from report_diagram_svg import build_report_diagram_svg
from module3_report_renderer import to_html

ui_selection = json.loads(ui_selection_json)
rows = json.loads(rows_json)
vci = json.loads(vci_json)
opts = json.loads(opts_json)
photos = opts.get("photos") or []
attachments = opts.get("attachments") or []
reference_tags = opts.get("reference_tags") or ["CSSB", "IRC R905.8"]
claim_name = opts.get("claim_name") or "Wood Shake Repair"

module2_result = build_scope_from_ui_selection(xml_text, ui_selection)
module1_result = {"affected_SF": module2_result.affected_SF_raw_total}

# v87: an estimate with carrier lines but ZERO in-scope ROOF lines is still a COMPARISON — every
# required item reads as missing — not a degrade to REQUIRED_SCOPE_ONLY. page 4 passes
# comparison_intended from page 3's mode (the single authority). With no in-scope rows,
# build_carrier_summary_from_manual_entry([]) yields a present-but-empty summary, which
# build_scope_comparison turns into the all-missing comparison. With no estimate at all (repair-scope),
# comparison_intended is false -> carrier_summary stays None -> REQUIRED_SCOPE_ONLY, unchanged.
carrier_summary = (build_carrier_summary_from_manual_entry(rows)
                   if (rows or opts.get("comparison_intended")) else None)

comparison = build_scope_comparison(module2_result, carrier_summary)
argument = build_scope_argument(module1_result, module2_result, comparison, carrier_summary, vci,
                                photos=photos, attachments=attachments,
                                reference_tags=reference_tags)["argument_pack"]
# The report's picture AND its percentage come from the SAME layout + diagram data the page-2 totals
# come from — never re-derived, never a placeholder. Failure to draw must not cost the report.
_diagram = None
_svg = ""
try:
    _layout = build_roof_layout(xml_text)
    _diagram = build_diagram_data(xml_text, ui_selection)
    _svg = build_report_diagram_svg(_layout, _diagram)
except Exception:
    _diagram = None
    _svg = ""
_pct = ((_diagram or {}).get("summary") or {}).get("pct_of_roof")

projection = build_module3_inputs(module1_result, module2_result, comparison, argument, vci,
                                  carrier_summary, photos=photos, attachments=attachments,
                                  reference_tags=reference_tags, diagram_pct=_pct)
if _svg:
    projection["inputs"]["P3"]["diagram_svg"] = _svg

rendered = render_module3_report(projection)
mode = projection["sc"]["mode"]

# The measured shake profile drives §3's shake-count derivation (per-shake coverage + shakes/SQ).
# It rides along in the ui_selection the scope was built from — the SAME measurements Module 2 used —
# so the derivation is never on the defaults. Presentation only; no computed value depends on it.
shake_measurements = ui_selection.get("shake_measurements") or ui_selection.get("shake_profile") or {}
# Per-device branding (base64 logo + typed attribution), read from localStorage above. Presentation only.
logo_data_uri = brand_logo or None
prepared_by = brand_prepared_by or None

# The §10.5 language guard governs export — we call it, never bypass or duplicate it.
export = safe_export(projection["inputs"]["P3"],
                     render_fn=lambda: to_html(rendered, mode, claim_name,
                                               {"kind": "PRODUCTION", "detail": "live claim"},
                                               logo_data_uri=logo_data_uri,
                                               prepared_by=prepared_by,
                                               shake_measurements=shake_measurements))

lines = ((comparison.get("scope_comparison") or {}).get("lines")) or []
out = {
    "mode": mode,
    "status": comparison["status"],
    "carrier_parser_status": (carrier_summary or {}).get("parser_status"),
    "duplicate_comparison_categories": list((carrier_summary or {}).get("duplicate_comparison_categories", []) or []),
    "gated": bool(rendered.get("gated")),
    "sections": sorted(rendered.get("sections") or []),
    "exported": bool(export["exported"]),
    "language_gate_hard": list(export["gate"]["hard"]),
    "html": export["artifact"] if export["exported"] else "",
    "lines": _wb_to_plain(lines),
}
json.dumps(out)
`, {
    xml_text: xmlText,
    ui_selection_json: JSON.stringify(uiSelection || {}),
    rows_json: JSON.stringify(carrierRows || []),
    vci_json: JSON.stringify(vci || {}),
    opts_json: JSON.stringify(opts || {}),
    brand_logo: brandLogo,
    brand_prepared_by: brandPreparedBy,
  });
}

// parseCarrierEstimate: LAYER A. Raw estimate text (from pdf.js on page 1) -> claim header +
// line items + proposed categories. Never fabricates: unfound header fields come back blank and
// an unmappable line comes back with category null + needs_mapping true. Empty/garbage text ->
// status TEXT_LAYER_ABSENT so page 3 can degrade to manual entry.
export async function parseCarrierEstimate(estimateText) {
  return runJson(`
import json
from carrier_layer_a import parse_carrier_estimate_text
json.dumps(_wb_to_plain(parse_carrier_estimate_text(estimate_text)))
`, { estimate_text: estimateText || "" });
}

// v73 DEFECT 1: the ONE operation authority, reachable from the manual entry paths. page 3 calls this
// on the description the user types (add AND edit) instead of hard-coding R&R — no second derivation.
export async function proposeOperation(description) {
  return runJson(`
import json
from carrier_layer_a import propose_operation
json.dumps(propose_operation(description))
`, { description: description || "" });
}

// v73 DEFECT 2: the hand-entry unit dropdown is DERIVED from the parser's own _UNITS list, so the
// dropdown and the parser cannot drift. Adding a unit to carrier_layer_a._UNITS makes it selectable.
export async function carrierUnitList() {
  return runJson(`
import json
from carrier_layer_a import UNIT_LIST
json.dumps(list(UNIT_LIST))
`, {});
}

// v75: which carrier categories resolve to MORE THAN ONE operation (Detach & Reset + new material),
// so page 3 can flag the ambiguity for review BEFORE the report is delivered. One authority: the same
// _partition_operations the approved side uses.
export async function mixedOperationCategories(rows) {
  return runJson(`
import json
from manual_carrier_entry import mixed_operation_categories
json.dumps(mixed_operation_categories(rows))
`, { rows: rows || [] });
}

globalThis.WoodShakePyodideBridge = {
  ready, bundledXmlText, roofLayout, scopeFromSelection, diagramData,
  workbenchUpdate, yagerUiSelection, yagerScope,
  requiredScope, buildCarrierSummary, buildScopeComparison, buildModule3Report, transitionStates,
  parseCarrierEstimate,
};
