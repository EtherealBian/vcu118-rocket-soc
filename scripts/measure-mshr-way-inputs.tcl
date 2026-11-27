# Read-only observation of the baseline's S1 timing budget, never alter the design.
if {$argc != 2} {error {usage: post_opt.dcp fresh-output-directory}}
lassign $argv dcp out
if {![file isfile $dcp] || [file exists $out]} {error {invalid input or non-fresh output}}
set_param general.maxThreads 2
open_checkpoint $dcp
if {[get_property PART [current_design]] ne {xcvu9p-flga2104-2L-e}} {error {unexpected part}}
set sys [get_clocks -quiet clk_out1_harnessSysPLL]
if {[llength $sys]!=1 || abs([get_property PERIOD $sys]-1000.0/175)>0.005} {error {wrong clock}}
set base chiptop0/system/tile_prci_domain/element_reset_domain_boom_tile/dcache
set clks [get_clocks -quiet -of_objects [get_pins -quiet [format {%s/s2_tag_match_way_0_reg[0]/C} $base]]]
if {$clks ne $sys} {error "wrong destination clock $clks"}
file mkdir $out
set t [open [file join $out paths.tsv] {WRONLY CREAT EXCL}]
puts $t "sink\tbit\tfrom\tto\tlevels\tdata_ns\tslack_ns\trequirement_ns"
foreach {name width} {s2_tag_match_way_0_reg 8 s2_replaced_way_en_REG_reg 3} {
 for {set i 0} {$i<$width} {incr i} {
  set path [format {%s/%s[%d]/D} $base $name $i]; set pin [get_pins -quiet $path]
  if {[llength $pin]!=1 || $pin ne $path} {error "bad pin $path"}
  set p [get_timing_paths -quiet -from $sys -to $pin -delay_type max -max_paths 1]
  if {[llength $p]!=1} {error "no unique path to $path"}
  set values [list]; foreach prop {STARTPOINT_PIN ENDPOINT_PIN LOGIC_LEVELS DATAPATH_DELAY SLACK REQUIREMENT} {lappend values [get_property $prop $p]}
  puts $t [join [concat [list $name $i] $values] "\t"]
  report_timing -from $sys -to $pin -delay_type max -input_pins -max_paths 1 -file [file join $out $name-$i.rpt]
 }
}
close $t; puts MSHR_WAY_BASELINE_S1_CHECKPOINT_QUERY_COMPLETE; close_design
