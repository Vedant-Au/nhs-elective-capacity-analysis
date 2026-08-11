Attribute VB_Name = "SolverSetup"
' NHS Cheshire & Merseyside Capacity Optimizer — Solver automation macro.
'
' What this does: programmatically runs the exact Data > Solver setup that's
' already documented cell-by-cell on the 'Solver Model' tab (objective cell,
' decision variable range, all 6 constraints) using Excel's standard Solver
' VBA API (SolverReset / SolverOk / SolverAdd / SolverSolve — unchanged since
' Excel 97, not a reverse-engineered format), then solves.
'
' Requires: the Solver add-in enabled (File > Options > Add-ins > Manage:
' Excel Add-ins > Go > tick "Solver Add-in") AND, in the VBA editor,
' Tools > References > tick "SOLVER" (or "Solver.xlam") — otherwise these
' calls raise "Sub or Function not defined".
'
' How to add this to the workbook:
'   1. Open the workbook in Excel.
'   2. Alt+F11 to open the VBA editor.
'   3. Insert > Module, paste this entire file's contents.
'   4. Tools > References, tick Solver (see note above).
'   5. Close the VBA editor. Ctrl+S — Excel will prompt to save as a
'      macro-enabled workbook (.xlsm); accept that.
'   6. Run it: Developer tab > Macros > RunCapacityOptimizerSolver > Run
'      (or press F5 with the cursor inside the Sub in the VBA editor).
'
' Cell references match scripts/build_solver_workbook.py exactly — if the
' workbook layout ever changes (e.g. providers added/removed), regenerate
' both the workbook and this macro from that script rather than hand-editing
' just one of them out of sync with the other.

Sub RunCapacityOptimizerSolver()

    SolverReset

    ' Objective: maximize total reduction in RTT over-52-week breaches (L19)
    ' by changing the 36 decision variable cells (3 levers x 12 providers).
    SolverOk SetCell:="$L$19", MaxMinVal:=1, ValueOf:=0, _
             ByChange:="$I$6:$K$17", Engine:=1, EngineDesc:="Simplex LP"

    ' Constraint 1 — budget: total cost (N19) <= budget (E24)
    SolverAdd CellRef:="$N$19", Relation:=1, FormulaText:="$E$24"

    ' Constraint 2 — equity: the equity-check cell (E28) must stay >= 0
    ' (higher-deprivation providers' reduction share can't fall more than
    ' the bounded tolerance below their baseline breach share)
    SolverAdd CellRef:="$E$28", Relation:=3, FormulaText:="0"

    ' Constraints 3-5 — each lever capped per provider
    SolverAdd CellRef:="$I$6:$I$17", Relation:=1, FormulaText:="$E$6:$E$17"   ' in-house
    SolverAdd CellRef:="$J$6:$J$17", Relation:=1, FormulaText:="$F$6:$F$17"   ' outsourcing
    SolverAdd CellRef:="$K$6:$K$17", Relation:=1, FormulaText:="$G$6:$G$17"   ' diagnostic

    ' Constraint 6 — non-negativity
    SolverAdd CellRef:="$I$6:$K$17", Relation:=3, FormulaText:="0"

    ' Re-assert the objective/engine (SolverAdd calls can reset some state)
    SolverOk SetCell:="$L$19", MaxMinVal:=1, ValueOf:=0, _
             ByChange:="$I$6:$K$17", Engine:=1, EngineDesc:="Simplex LP"

    ' Solve and keep the result without showing Solver's results dialog
    SolverSolve UserFinish:=True

    MsgBox "Solver finished. Objective cell L19 (Solver Model tab) now holds " & _
           "the re-optimized total reduction. Compare it to the pre-filled " & _
           "reference value already in the file — they should match closely " & _
           "under the default assumptions, and will differ once you change " & _
           "the budget or any Assumption cell.", vbInformation, "Capacity Optimizer"

End Sub
