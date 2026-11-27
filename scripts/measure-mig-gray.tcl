# Characterize all ten 4-bit AXI asynchronous FIFO pointer transfers in a *copy in
# memory* of a routed design. No checkpoint, netlist, hardware or bitstream writes.
if {$argc ni {2 3}} {error {usage: routed.dcp fresh-output-directory ?100|175?}}
lassign $argv dcp out mhz
if {$argc == 2} {set mhz 100}
if {$mhz ni {100 175}} {error {unsupported system clock contract}}
if {![file isfile $dcp] || [file exists $out]} {error {missing checkpoint or stale output directory}}
file mkdir $out; set_param general.maxThreads 2; open_checkpoint $dcp
set sys clk_out1_harnessSysPLL; set ui mmcm_clkout0
foreach clk [list $sys $ui] p [list [expr {1000.0/$mhz}] 5.0] {
 set c [get_clocks $clk]; if {[llength $c]!=1 || abs([get_property PERIOD $c]-$p)>0.001} {error "wrong clock $clk"}
}
proc one_fd {name} {
 set c [get_cells [list $name]]; if {[llength $c]!=1 || $c ne $name || ![string match FD* [get_property REF_NAME $c]]} {error "missing exact FF: $name"}; return $c
}
set f [open [file join $out bits.tsv] {WRONLY CREAT EXCL}]; puts $f "channel\tpointer\tbit\tlaunch_clock\tcapture_clock\tlaunch\tcapture"
set g [open [file join $out data-delays.tsv] {WRONLY CREAT EXCL}]; puts $g "channel\tpointer\tbit\tcorner\tdata_ns\tlogic_levels"
foreach ch {aw w b ar r} {
 set forward [expr {$ch in {aw w ar}}]; set iface [expr {$forward ? "nodeOut_$ch" : "nodeIn_$ch"}]
 foreach ptr {widx ridx} {
  set write [expr {$ptr eq "widx"}]; set fromsys [expr {$write == $forward}]
  set s [expr {$fromsys ? "mig/axi4asource" : "mig/island/axi4asink"}]; set d [expr {$fromsys ? "mig/island/axi4asink" : "mig/axi4asource"}]
  set a [expr {$fromsys ? $sys : $ui}]; set b [expr {$fromsys ? $ui : $sys}]
  set source [expr {$write ? "source" : "sink"}]; set sink [expr {$write ? "sink" : "source"}]; set src {}; set dst {}
  for {set bit 0} {$bit<4} {incr bit} {
   set tail [expr {$bit ? "_$bit" : ""}]
   set x [one_fd [format {%s/%s_%s/%s_gray_reg[%d]} $s $iface $source $ptr $bit]]
   set y [one_fd [format {%s/%s_%s/%s_%s_gray/output_chain%s/sync_2_reg} $d $iface $sink $ptr $ptr $tail]]
   foreach ff [list $x $y] clk [list $a $b] {if {[get_clocks -of_objects [get_pins $ff/C]] ne $clk} {error "wrong clock $ff"}}
   set drivers [get_pins -leaf -of_objects [get_nets -segments -of_objects [get_pins $y/D]] -filter {DIRECTION == OUT}]
   if {[llength $drivers]!=1 || $drivers ne "$x/Q"} {error "not a direct same-bit connection $x -> $y: $drivers"}
   puts $f [join [list $ch $ptr $bit $a $b $x $y] "\t"]; lappend src $x; lappend dst $y
  }
  # A conservative characterization threshold of one faster-clock period.
  # set_bus_skew is independent of the clock-group exception. We do not replace
  # clock groups/override data-path delay or claim FIFO/CDC sign-off.
  foreach k {max min} {
   set paths [get_timing_paths -from [get_cells $src] -to [get_cells $dst] -user_ignored -delay_type $k -max_paths 16 -nworst 1]
   if {[llength $paths]!=4} {error "wrong number of direct ignored paths $ch:$ptr $k"}
   set seen {}; foreach path $paths {
    set a_pin [get_property STARTPOINT_PIN $path]; set b_pin [get_property ENDPOINT_PIN $path]
    set i [lsearch -exact $src [file dirname $a_pin]]
    if {$i<0 || $a_pin ne "[lindex $src $i]/C" || $b_pin ne "[lindex $dst $i]/D" || [get_property LOGIC_LEVELS $path]!=0} {error "nonmatching Gray bit: $a_pin -> $b_pin"}
    lappend seen $i; puts $g [join [list $ch $ptr $i $k [get_property DATAPATH_DELAY $path] [get_property LOGIC_LEVELS $path]] "\t"]
   }; if {[lsort -integer $seen] ne {0 1 2 3}} {error "duplicate bit $ch:$ptr $k"}
  }
  set_bus_skew -from [get_cells $src] -to [get_cells $dst] 5.0
 }
}; close $f; close $g
report_bus_skew -delay_type min_max -max_paths 4 -path_type short -file [file join $out bus-skew.rpt]
close_design; puts MIG_GRAY_DIAGNOSTIC_SKEW_REPORT_COLLECTED
