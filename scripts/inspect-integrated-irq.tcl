# Read-only inspection of the *integrated* tile interrupt receiver in one DCP.
# It is not a whole-design CDC waiver. No design, constraint, or hardware writes.
if {$argc != 3} {error {usage: <checkpoint> <inspect|audit-marked|require-marked> <fresh TSV>}}
lassign $argv file mode out
if {![file isfile $file] || [file exists $out] || $mode ni {inspect audit-marked require-marked}} {error {invalid inputs}}
set_param general.maxThreads 2
open_checkpoint $file
set chain chiptop0/system/tile_prci_domain/intsink/chain/output_chain
set launch chiptop0/system/tlDM/dmOuter/dmOuter/debugIntRegs_0_reg
proc leafpins {pin direction} {
 set nets [get_nets -quiet -segments -of_objects [get_pins $pin]]
 if {![llength $nets]} {error "unconnected pin $pin"}
 return [lsort -unique [get_property NAME [get_pins -quiet -leaf -of_objects $nets -filter "DIRECTION == $direction"]]]
}
set cells [get_cells -hier -quiet -filter "IS_PRIMITIVE && NAME =~ $chain/*"]
if {![llength $cells]} {error "no primitives at $chain"}
set counts [dict create FD 0 SRL 0 TIE 0 OTHER 0]; set f [open $out {WRONLY CREAT EXCL}]
puts $f "cell\tprimitive\tasync_reg\tlocation"
foreach c [lsort $cells] {
 set r [get_property REF_NAME $c]; set a [get_property -quiet ASYNC_REG $c]; set l [get_property -quiet LOC $c]
 set kind OTHER; if {[string match FD* $r]} {set kind FD} elseif {[string match SRL* $r]} {set kind SRL} elseif {$r in {GND VCC}} {set kind TIE}
 dict incr counts $kind; puts $f [join [list $c $r $a $l] "\t"]
}; close $f; puts "INTEGRATED_IRQ_LEAF_COUNTS $counts"
if {$mode ne "inspect"} {
 if {[dict get $counts FD]!=3 || [dict get $counts SRL]!=0 || [dict get $counts OTHER]!=0} {error "unexpected primitives $counts"}
 set clocks {}; foreach i {2 1 0} {
  # Rebuilt hierarchy may suffix the exact register name with __0.
  set matches {}; foreach c $cells {if {[regexp [format {^sync_%d_reg(__[0-9]+)?$} $i] [file tail $c]] && [string match FD* [get_property REF_NAME $c]]} {lappend matches $c}}
  if {[llength $matches]!=1} {error "ambiguous stage $i: $matches"}; set cell [lindex $matches 0]; set stage($i) $cell; if {[get_property ASYNC_REG $cell] ni {1 true TRUE}} {error "unmarked $cell"}
  set clk [get_clocks -quiet -of_objects [get_pins $cell/C]]; if {[llength $clk]!=1} {error "no unique clock at $cell/C"}; lappend clocks $clk
 }
 if {[lsort -unique $clocks] ne {clk_out1_harnessSysPLL}} {error "wrong destination clocks $clocks"}
 foreach {src dst} [list $stage(2) $stage(1) $stage(1) $stage(0)] {
  set drivers [leafpins $dst/D OUT]; if {$drivers ne "$src/Q"} {error "wrong driver of $dst/D: $drivers"}
  # The debug request source may also have local consumers; no other logic
  # may sample a metastability stage before it reaches the next flip-flop.
  if {$src ne $launch} {set loads [leafpins $src/Q IN]; if {$loads ne "$dst/D"} {error "extra interstage load(s) $loads"}}
 }
 puts INTEGRATED_IRQ_MARKED_INTERSTAGES_VERIFIED
 set srcpin [leafpins $stage(2)/D OUT]; if {[llength $srcpin]!=1} {error "ambiguous receiver launch pins: $srcpin"}
 if {$srcpin eq "$launch/Q"} {
  puts INTEGRATED_IRQ_THREE_MARKED_FFS_CHAIN_VERIFIED
 } else {
  set comb [get_cells -of_objects [get_pins $srcpin]]; set ref [get_property REF_NAME $comb]; set init [get_property -quiet INIT $comb]
  puts "INTEGRATED_IRQ_FIRST_STAGE_DRIVER $srcpin REF=$ref INIT=$init"
  set names {}; set cx {}; foreach pin [get_pins -of_objects $comb -filter {DIRECTION == IN}] {
   set driven [leafpins $pin OUT]; if {[llength $driven]!=1} {error "unresolved input $pin = $driven"}
   set ff [get_cells -of_objects [get_pins $driven]]; set clocks [get_clocks -quiet -of_objects [get_pins -quiet $ff/C]]
   puts "INTEGRATED_IRQ_LUT_INPUT $pin driver=$driven REF=[get_property REF_NAME $ff] clock=$clocks"
   lappend names $driven; lappend cx $clocks
  }
  set local chiptop0/system/tlDM/dmInner/dmInner/hrDebugIntReg_0_reg/Q
  if {$ref ne "LUT2" || ![regexp -nocase {^4'h[e]$} $init] || [lsort $names] ne [lsort [list $launch/Q $local]] || [lsort $cx] ne [lsort {JTCK clk_out1_harnessSysPLL}]} {error {unclassified combinational front end; inspect exact pins}}
  puts INTEGRATED_IRQ_COMBINED_ASYNC_AND_LOCAL_SOURCES_NOT_CDC_SIGNOFF
  if {$mode eq "require-marked"} {error {registered first-stage source required; mixed-clock OR remains}}
 }
}
close_design
