# Require the registered JTCK launch to reach the first metastability FF directly;
# prove local and remote requests meet only *after* two destination clock edges.
# Called from inspect-integrated-irq.tcl after the three tile stages were checked.
proc require_split_irq {tile_d launch} {
 set base chiptop0/system/tlDM/vcu_halt_merge
 set sys clk_out1_harnessSysPLL
 set local chiptop0/system/tlDM/dmInner/dmInner/hrDebugIntReg_0_reg
 foreach {name cx} [list $launch JTCK $local $sys] {
  set c [get_cells -quiet $name]; if {[llength $c]!=1 || ![string match FD* [get_property REF_NAME $c]]} {error "missing launch FF $name"}
  if {[get_clocks -quiet -of_objects [get_pins $c/C]] ne $cx} {error "unexpected launch clock $c"}
 }
 foreach name {halt_meta halt_clean local_d1 local_d2} {
  set c [get_cells -quiet $base/${name}_reg]; if {[llength $c]!=1 || ![string match FD* [get_property REF_NAME $c]]} {error "missing split FF: $name"}
  if {[get_clocks -quiet -of_objects [get_pins $c/C]] ne $sys} {error "wrong receiving clock $c"}
  set marked [expr {[get_property -quiet ASYNC_REG $c] in {1 true TRUE}}]
  if {$marked != [string match halt_* $name]} {error "wrong metastability-chain membership $c"}; set stage($name) $c
 }
 foreach {prev dest} [list $launch $stage(halt_meta) $stage(halt_meta) $stage(halt_clean) $local $stage(local_d1) $stage(local_d1) $stage(local_d2)] {
  if {[leafpins $dest/D OUT] ne "$prev/Q"} {error "not directly registered $prev -> $dest"}
 }
 foreach {prev dest} [list $stage(halt_meta) $stage(halt_clean) $stage(local_d1) $stage(local_d2)] {
  if {[leafpins $prev/Q IN] ne "$dest/D"} {error "unexpected first-stage fanout at $prev"}
 }
 set q [leafpins $tile_d OUT]; if {[llength $q]!=1} {error "ambiguous merge output: $q"}
 set gate [get_cells -of_objects [get_pins $q]]
 if {[get_property REF_NAME $gate] ne "LUT2" || ![regexp -nocase {^4'hE$} [get_property INIT $gate]]} {error "not the reviewed two-input OR at $tile_d"}
 set drivers {}; foreach p [get_pins -of_objects $gate -filter {DIRECTION == IN}] {set src [leafpins $p OUT]; if {[llength $src]!=1} {error "ambiguous OR input $p"}; lappend drivers $src}
 if {[lsort $drivers] ne [lsort [list $stage(halt_clean)/Q $stage(local_d2)/Q]]} {error "OR before synchronization or unclassified source(s) $drivers"}
 puts "IRQ_REMOTE_TRACE $launch/Q $stage(halt_meta)/D $stage(halt_clean)/D"
 puts "IRQ_LOCAL_TRACE $local/Q $stage(local_d1)/D $stage(local_d2)/D"
 puts "IRQ_OR_IN_DESTINATION_DOMAIN $drivers -> $q -> $tile_d"
 puts INTEGRATED_SPLIT_HALT_SOURCES_VERIFIED_NOT_WHOLE_DESIGN_CDC_SIGNOFF
}
