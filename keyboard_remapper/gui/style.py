CSS = """
.keychip {
  background: alpha(@window_fg_color, 0.07);
  border: 1px solid alpha(@window_fg_color, 0.16);
  border-bottom-width: 2px;
  border-radius: 7px;
  padding: 2px 9px;
  min-height: 22px;
  font-weight: 600;
}
.keychip.accent {
  background: alpha(@accent_bg_color, 0.20);
  border-color: alpha(@accent_bg_color, 0.55);
  color: @accent_color;
}
.keychip.big { padding: 4px 13px; min-height: 28px; font-size: 1.1em; border-radius: 9px; }
.chip-plus { opacity: 0.45; margin: 0 1px; }
.chord-button { padding: 4px 10px; }
.editor-card { background: @card_bg_color; border-radius: 16px; padding: 18px 20px;
               box-shadow: 0 0 0 1px alpha(@window_fg_color, 0.08); }
.editor-title { font-weight: 700; font-size: 1.05em; }
.dim { opacity: 0.62; }
.summary-line { font-size: 1.02em; }
.layer-bar label.caption-heading { opacity: 0.7; }
.mapping-row { padding: 8px 10px; border-radius: 10px; }
.mapping-arrow { opacity: 0.5; }
.recording { background: alpha(@destructive_bg_color, 0.14); color: @destructive_color; }
.step-row { padding: 4px 0; }
.empty-hint { padding: 26px 8px; }
.kb-frame { padding: 2px; }
.legacy-banner { background: alpha(@accent_bg_color, 0.18); padding: 8px 14px; }
.sort-header { font-weight: 700; font-size: 0.85em; opacity: 0.75; padding: 2px 6px; min-height: 0; }
.drop-before { box-shadow: inset 0 2px 0 0 @accent_bg_color; }
.drop-after { box-shadow: inset 0 -2px 0 0 @accent_bg_color; }
.status-pill { border-radius: 99px; padding: 2px 10px; font-size: 0.85em; font-weight: 600; }
.status-pill.on { background: alpha(@success_bg_color, 0.22); color: @success_color; }
.status-pill.off { background: alpha(@window_fg_color, 0.09); }
.picker-list row { padding: 2px 6px; border-radius: 8px; }
.picker-header { font-weight: 700; opacity: 0.6; font-size: 0.82em; padding: 10px 8px 3px 8px; }
"""
