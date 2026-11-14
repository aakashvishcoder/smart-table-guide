#ifndef FINDTABLE_H
#define FINDTABLE_H

#include "table.h"

// first/second are table ids. second == -1 means a single table.
// Both -1 means nothing fits.
struct TableResult {
    int first;
    int second;
};

// Finds the free table, or pair of adjacent free tables, that seats
// `groupSize` with the fewest extra chairs; on a tie a single table beats a pair.
// Accessibility is ignored.
inline TableResult FindTable(int groupSize,
                             const table tables[], int numTables)
{
    TableResult best = { -1, -1 };
    int bestExtra = -1;  // -1 means nothing found yet

    for (int i = 0; i < numTables; ++i) {
        const table& t = tables[i];
        if (t.InUse()) continue;

        // Single table (also wins a tie against a pair)
        int extra = t.Chairs() - groupSize;
        if (extra >= 0 && (bestExtra < 0 || extra < bestExtra ||
                           (extra == bestExtra && best.second != -1))) {
            bestExtra = extra;
            best.first = t.Id();
            best.second = -1;
        }

        // Pair with each adjacent table
        int adj[2] = { t.Adjacent1(), t.Adjacent2() };
        for (int k = 0; k < 2; ++k) {
            if (adj[k] == -1) continue;
            for (int j = 0; j < numTables; ++j) {
                const table& u = tables[j];
                if (u.Id() != adj[k] || u.InUse()) continue;
                extra = t.Chairs() + u.Chairs() - groupSize;
                if (extra >= 0 && (bestExtra < 0 || extra < bestExtra)) {
                    bestExtra = extra;
                    best.first = t.Id();
                    best.second = u.Id();
                }
            }
        }
    }
    return best;
}

// Marks the table(s) in `r` as in use by calling Direct() on each.
// Does nothing if `r` is {-1, -1}.
inline void AssignTables(const TableResult& r, table tables[], int numTables)
{
    for (int i = 0; i < numTables; ++i) {
        int id = tables[i].Id();
        if (id == r.first || (r.second != -1 && id == r.second)) {
            tables[i].Direct();
        }
    }
}

#endif // FINDTABLE_H
