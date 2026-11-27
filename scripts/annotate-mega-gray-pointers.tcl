# Load only on a separately versioned candidate before implementation. No automatic invocation.
# Fails on any different primitive, driver, clock, interstage load, or annotation scope.
namespace eval ::vcu118_gray {
proc fd {name} {set c [get_cells -quiet [list $name]];if {[llength $c]!=1 || $c ne $name || ![string match FD* [get_property REF_NAME $c]]} {error "not exact FF $name"};return $c}
proc network {p} {return [get_nets -segments -of_objects [get_pins [list $p]]]}
proc direct {from to exclusive} {
    set nets [network $to/D]; set pins [get_pins -leaf -of_objects $nets -filter {DIRECTION == OUT}]
    if {[llength $pins]!=1 || $pins ne "$from/Q"} {error "wrong driver: $to/D $pins"}
    if {$exclusive} {set sinks [get_pins -leaf -of_objects $nets -filter {DIRECTION == IN}];if {[llength $sinks]!=1 || $sinks ne "$to/D" || [llength [get_ports -quiet -of_objects $nets]]} {error "unexpected interstage fanout $from -> $sinks"}}
}
proc labels {} {return [lsort [get_cells -quiet -hier -filter {IS_PRIMITIVE && ASYNC_REG == TRUE}]]}
proc pairs {cpu ddr} {
    set result {}
    foreach ch {aw w b ar r} {
        if {$ch in {aw w ar}} {set tx $cpu/nodeOut_${ch}_source; set rx $ddr/nodeOut_${ch}_sink} else {set tx $ddr/nodeIn_${ch}_source; set rx $cpu/nodeIn_${ch}_sink}
        foreach ptr {widx ridx} {
            if {$ptr eq "widx"} {set a $tx;set b $rx} else {set a $rx;set b $tx}
            for {set bit 0} {$bit<4} {incr bit} {
                set suffix [expr {$bit ? "_$bit" : ""}]
                lappend result [list $ch $ptr $bit [format {%s/%s_gray_reg[%d]} $a $ptr $bit] $b/${ptr}_${ptr}_gray/output_chain${suffix}/sync_2_reg]
            }
        }
    }
    return $result
}
proc annotate {profile audit} {
    if {![string match {2024.2*} [version -short]] || [get_property PART [current_project]] ne "xcvu9p-flga2104-2L-e"} {error {wrong tool or part}}
    switch -- $profile {
        probe {set top vcu_gray_probe;set cpu axi4asource;set ddr axi4asink;set sys sys;set ui ui}
        board {set top VCU118FPGATestHarness;set cpu mig/axi4asource;set ddr mig/island/axi4asink;set sys clk_out1_harnessSysPLL;set ui mmcm_clkout0}
        default {error {unsupported physical design}}
    }
    # current_design may return a run handle (e.g. design_1), not the netlist top.
    set header [report_clocks -return_string]
    if {![regexp -line {^\| Design +: ([^[:space:]]+)[ \t]*$} $header -> design] || $design ne $top ||
        ![regexp -line {^\| Design State +: Synthesized[ \t]*$} $header]} {error {expected the exact synthesized top}}
    set pairs [pairs $cpu $ddr]
    set before [labels];set targets {};set launches {}
    set actual {}
    foreach r $pairs {
        lassign $r ch ptr bit x y; set end [file dirname $y];set seq [list [fd $y] [fd $end/sync_1_reg] [fd $end/sync_0_reg]]
        set orig $x; set sources [get_pins -leaf -of_objects [network $y/D] -filter {DIRECTION == OUT}]; set alt [format {%s/%s_%s_bin_reg[3]} [file dirname $x] $ptr $ptr]
        if {$sources ne "$x/Q"} {if {$bit ne "3" || $sources ne "$alt/Q"} {error "wrong launch identity $orig -> $sources"};set x $alt};set s [fd $x]
        lappend actual [list $ch $ptr $bit $orig $s $y]
        if {![string match */sync_2_reg $y]} {error {unexpected entry stage}};set syswrite [expr {($ch in {aw ar w}) == ($ptr eq "widx")}];set sc [expr {$syswrite ? $sys : $ui}];set dc [expr {$syswrite ? $ui : $sys}]
        if {[get_clocks -of_objects [get_pins [list $s/C]]] ne $sc} {error "wrong launch clock $s"};set p $s;set reset "";set index 0
        foreach d $seq {
            if {[get_property REF_NAME $d] ne "FDCE" || [get_clocks -of_objects [get_pins [list $d/C]]] ne $dc} {error "wrong receiver $d"}
            set rst [lsort [network $d/CLR]];if {![llength $rst] || ($index && $rst ne $reset)} {error "reset differs within $end"};set reset $rst
            direct $p $d $index; set p $d;incr index
        }
        lappend launches $s;lappend targets {*}$seq
    }
    if {[llength [lsort -unique $targets]]!=120 || [llength [lsort -unique $launches]]!=40 || [llength $pairs]!=40} {error {wrong coverage}}
    foreach p $targets {if {$p in $before || $p in $launches} {error {already tagged or not exclusive receiver}}}
    if {[file exists $audit]} {error {expected a fresh actual endpoint receipt}}
    set f [open $audit {WRONLY CREAT EXCL}];foreach row $actual {puts $f [join $row "\t"]};close $f
    set_property ASYNC_REG TRUE [get_cells $targets];if {[labels] ne [lsort [concat $before $targets]]} {error {annotation escaped approved set}}
    return [list $before $targets]
}
}
