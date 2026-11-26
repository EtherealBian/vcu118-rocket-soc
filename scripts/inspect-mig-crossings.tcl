# Audit ignored DDR UI/system timing paths without changing clocks or exceptions.
# No device operations, checkpoint writes, or sign-off decisions.
if {$argc != 2} {error {usage: inspect-mig-crossings.tcl routed.dcp fresh-output-directory}}
lassign $argv dcp out
if {![file isfile $dcp] || [file exists $out]} {error {require existing DCP and fresh output directory}}
file mkdir $out
open_checkpoint $dcp
set f [open [file join $out endpoints.tsv] {WRONLY CREAT EXCL}]; fconfigure $f -translation lf
puts $f "source_clock\tdestination_clock\tkind\tstart\tend\tdatapath_ns\tlogic_levels"
set clocks {clk_out1_harnessSysPLL mmcm_clkout0}
foreach a $clocks b [lreverse $clocks] {
 set src [get_clocks $a]; set dst [get_clocks $b]
 if {[llength $src] != 1 || [llength $dst] != 1} {error "unresolved clock pair $a -> $b"}
 foreach k {max min} {
  # One extremal path per endpoint, not all launch/capture combinations.
  set paths [get_timing_paths -from $src -to $dst -user_ignored -delay_type $k -max_paths 4096 -nworst 1]
  set n [llength $paths]; if {!$n || $n >= 4096} {error "empty or truncated ignored paths $a -> $b $k: $n"}
  foreach p $paths {
   set fields [list $a $b $k]; foreach prop {STARTPOINT_PIN ENDPOINT_PIN DATAPATH_DELAY LOGIC_LEVELS} {
    set v [get_property $prop $p]; if {$v eq {}} {error "missing path property $prop"}; lappend fields $v
   }; puts $f [join $fields "\t"]
  }; flush $f; puts "MIG_IGNORED_ENDPOINT_PATHS $a $b $k $n"
  report_timing -from $src -to $dst -user_ignored -delay_type $k -max_paths 3 -nworst 1 -file [file join $out "$a-$b-$k.rpt"]
 }
}
close $f; close_design
puts MIG_IGNORED_ENDPOINT_AUDIT_COLLECTED
