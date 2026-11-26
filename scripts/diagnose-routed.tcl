# Source from an open implemented design. Every table is specific to this checkpoint.
proc vcu_endpoint_reports {out} {
 if {[file exists $out]} {error "fresh report directory required: $out"}; file mkdir $out
 set f [open [file join $out endpoints.tsv] w]; puts $f "destination_clock\tkind\tslack_ns\tlogic_levels\tfrom\tto"
 foreach clock [get_clocks] {
  set name [get_property NAME $clock]; regsub -all {[^a-zA-Z0-9._-]} $name _ slug
  foreach kind {max min} {
   set paths [get_timing_paths -quiet -to $clock -delay_type $kind -max_paths 40 -nworst 1]; if {![llength $paths]} continue
   foreach path $paths {puts $f [join [list $name $kind [get_property SLACK $path] [get_property LOGIC_LEVELS $path] [get_property STARTPOINT_PIN $path] [get_property ENDPOINT_PIN $path]] "\t"]}; flush $f
   report_timing -to $clock -delay_type $kind -max_paths 8 -nworst 1 -input_pins -nets -file [file join $out "$slug-$kind.rpt"]
  }
 }; close $f
}
