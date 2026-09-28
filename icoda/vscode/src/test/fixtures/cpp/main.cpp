volatile int count = 0;

void C() { ++count; }
void B() { C(); }
void D() { ++count; }
void A() { B(); D(); }
void E() { ++count; }
int main() { A(); E(); return count == 3 ? 0 : 1; }
