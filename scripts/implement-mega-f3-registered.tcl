# Registered front-end logic only. No processor, I-cache RAM, board or SLR endpoints.
# Vivado 2024.2: -source this-script -tclargs prepared-dir fresh-dir [case [mode ...]]
# With one case: synth stops at synthesis; measure-synth or from-synth take
# the exact synthesized.dcp and SHA-256, to remeasure it or implement it.
if {$argc ni {2 3 4 6}} {error {usage: qualified-inputs fresh-output ?case ?synth | from-synth/measure-synth dcp sha256??}}
set mode all
if {$argc==4} {set mode [lindex $argv 3]; if {$mode ne "synth"} {error {explicit synth mode required}}}
if {$argc==6} {lassign [lrange $argv 3 end] mode dcp sha;set dcp [file normalize $dcp]; if {$mode ni {from-synth measure-synth} || ![regexp {^[0-9a-f]{64}$} $sha]} {error {expected a qualified synthesis checkpoint and digest}}}
set cases {stock prefix_and_compare eligible_lanes}
if {$argc>=3} {set one [lindex $argv 2];if {$one ni $cases} {error {unqualified case}};set cases [list $one]}
lassign $argv in out; set in [file normalize $in]; set out [file normalize $out]
if {[file exists $out] || ![string match {2024.2*} [version -short]]} {error {requires new output and Vivado 2024.2}}
set checker [file join [file dirname [file normalize [info script]]] test-mega-f3-registered.py]
if {[exec python -I -B $checker --check-prepared $in] ne {F3_REGISTERED_INPUTS_VERIFIED}} {error {different experiment inputs}}
set file [open [file join $in required.tsv] r]; set lines [split [string trim [read $file]] "\n"]; close $file
if {[llength $lines]!=657 || [lindex $lines 0] ne "lane\tcapture\tdependent"} {error {invalid dependence map}}
foreach line [lrange $lines 1 end] {
    lassign [split $line "\t"] lane bit flag; dict set required $lane,$bit $flag
}
file mkdir $out; set_param general.maxThreads 2

# Preserve and identify even launch registers whose *data* the logic never uses.
proc bank {regs name count} {
    set result [dict create]; set rx [format {^%s_reg\[([0-9]+)\]$} $name]
    foreach reg $regs {
        if {[regexp $rx [get_property NAME $reg] -> bit]} {
            if {$bit>=$count || [dict exists $result $bit] || ![string match {FD*} [get_property REF_NAME $reg]]} {error "unexpected $name register: $reg"}
            dict set result $bit $reg
        }
    }
    if {[dict size $result]!=$count} {error "retained [dict size $result]/$count $name registers"}; return $result
}

proc collect {f tag starts pins type required} {
    # -nworst 1 gives at most one path to each D pin. Compare the same 82
    # destinations including the CFI/mask endpoints, even when a group is faster.
    set paths [get_timing_paths -quiet -from $starts -to $pins -delay_type $type -max_paths 82 -nworst 1]
    set seen [dict create]
    foreach p $paths {
        set dst [get_property ENDPOINT_PIN $p]; set src [get_property STARTPOINT_PIN $p]
        if {![regexp {^capture_reg\[([0-9]+)\]/D$} $dst -> b] || $b>=82 || [dict exists $seen $b]} {error "unexpected endpoint $dst in $tag"}
        if {![regexp {^launch_reg\[([0-9]+)\]/[CQ]$} $src -> s] || $s>=556 || ($tag ne "all" && $s!=$tag)} {error "unexpected startpoint $src in $tag"}
        dict set seen $b [list $s [get_property SLACK $p] [get_property DATAPATH_DELAY $p] [get_property LOGIC_LEVELS $p]]
    }
    for {set b 0} {$b<82} {incr b} {
        set must [expr {$tag eq "all" ? 1 : [dict get $required $tag,$b]}]
        if {[dict exists $seen $b]} {
            set data [dict get $seen $b]; puts $f [join [list $tag $type $b $must path {*}$data] "\t"]
        } else {
            if {$must} {error "missing semantically required $type path from $tag to $b"}
            puts $f [join [list $tag $type $b $must no_path - - - -] "\t"]
        }
    }
}
foreach name $cases {
    set work [file join $out $name]; file mkdir $work; cd $work
    if {$mode ni {from-synth measure-synth}} {
        create_project -in_memory -part xcvu9p-flga2104-2L-e
        read_verilog [file join $in $name.v]; read_verilog [file join $in boundary.v]; read_xdc [file join $in clock.xdc]
        synth_design -mode out_of_context -top f3_boundary -part xcvu9p-flga2104-2L-e
        write_checkpoint synthesized.dcp
        report_timing_summary -file synthesized-timing.rpt
    } else {
        if {[file tail $dcp] ne "synthesized.dcp" || [file tail [file dirname $dcp]] ne $name} {error {wrong synthesis case or stage}}
        set check {import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())}
        if {[exec python -I -B -c $check $dcp] ne $sha} {error {changed synthesis checkpoint}}
        puts "F3_INPUT_SYNTH_SHA256 $name $sha";open_checkpoint $dcp
    }
    set estimating [expr {$mode in {synth measure-synth}}]
    if {!$estimating} {
        opt_design; place_design; route_design
        report_route_status -file route.rpt
    }
    report_timing_summary -report_unconstrained -file timing.rpt; report_utilization -file util.rpt
    set clk [get_clocks -quiet cpu]
    if {[llength $clk]!=1 || abs([get_property PERIOD $clk]-5.714)>0.0001} {error {wrong clock}}
    set regs [all_registers -clock $clk]; set launches [bank $regs launch 556]; set captures [bank $regs capture 82]
    if {[llength $regs]!=638} {error {unexpected registers in combinational experiment}}
    set pins [get_pins -of_objects [dict values $captures] -filter {REF_PIN_NAME == D}]
    if {[llength $pins]!=82} {error {expected 82 distinct capture D pins}}
    set f [open paths.tsv {WRONLY CREAT EXCL}]; puts $f "group\ttype\tcapture_bit\tfunctional_dependence_required\tstatus\tlaunch_bit\tslack_ns\tdata_ns\tlogic_levels"
    foreach type {max min} {
        collect $f all [dict values $launches] $pins $type $required
        report_timing -from [dict values $launches] -to $pins -delay_type $type -max_paths 10 -nworst 1 -input_pins -file registers-$type.rpt
    }
    for {set lane 0} {$lane<8} {incr lane} {collect $f $lane [dict get $launches $lane] $pins max $required}
    close $f
    if {$estimating} {close_project;puts "F3_REGISTERED_SYNTH_ONLY $name"} else {
        write_checkpoint registers-routed.dcp; close_project; puts "F3_REGISTERED_CASE_COLLECTED $name"
    }
}
if {$mode in {synth measure-synth}} {puts F3_REGISTERED_SYNTH_FINISHED_NOT_ROUTE} elseif {[llength $cases]==3} {puts F3_REGISTERED_THREE_CASES_COLLECTED_NOT_SOC} else {puts "F3_REGISTERED_SINGLE_CASE_COLLECTED_NOT_SOC $one"}
