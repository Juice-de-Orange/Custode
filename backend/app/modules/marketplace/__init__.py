"""marketplace — handelbare Haushaltsaufgaben mit Escrow (KONZEPT §5.10).

Importiert nur kernel/* und die PUBLIC api.py von tasks (Instanz prüfen/neu zuweisen) + economy
(Escrow buchen) — nie deren Interna, nie ein anderes Modul direkt. Kein Modul importiert marketplace
(einseitige Abhängigkeit, kein Zyklus)."""
