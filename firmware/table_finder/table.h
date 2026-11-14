#ifndef TABLE_H
#define TABLE_H

class table {
public:
    table(int tableId, int numChairs, int adjacent1 = -1, int adjacent2 = -1,
          int angleFromCenter = 0, bool accessibility = false, bool inUse = false)
        : id(tableId), chairs(numChairs), adjacentId1(adjacent1),
          adjacentId2(adjacent2), angleFromCenter(angleFromCenter),
          inUse(inUse), accessibility(accessibility) {}

    bool InUse() const { return inUse; }
    int  Direct() { inUse = true; return id; }
    int  Angle() const { return angleFromCenter; }
    void Clear() { inUse = false; }

    int  Id() const { return id; }
    int  Chairs() const { return chairs; }
    bool Accessible() const { return accessibility; }
    int  Adjacent1() const { return adjacentId1; }
    int  Adjacent2() const { return adjacentId2; }

private:
    int  id, chairs, adjacentId1, adjacentId2, angleFromCenter;
    bool inUse, accessibility;
};

#endif // TABLE_H
