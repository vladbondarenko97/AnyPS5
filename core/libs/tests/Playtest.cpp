#include <cstdlib>
#include <stdexcept>

extern "C" void NotImplemented_nid_no_patch(const char* funcName);
extern "C" bool PlaytestSkip_nid_no_patch(const char* kind, const char* reason);

static void Require(bool value) { if (!value) std::abort(); }

int main(int argc, char**) {
    const bool playtest = argc > 1;
    Require(PlaytestSkip_nid_no_patch("draw", "first line\nsecond line") == playtest);
    bool threw = false;
    try {
        NotImplemented_nid_no_patch("PlaytestProbe");
    } catch (const std::runtime_error&) {
        threw = true;
    }
    Require(threw != playtest);
    return 0;
}
