// NCU solar position using only the C++ standard library.
// Build: g++ -std=c++20 solar_position_offline.cpp -o solar_position_offline
// Solar position model: https://gml.noaa.gov/grad/solcalc/calcdetails.html

#include <algorithm>
#include <chrono>
#include <cmath>
#include <iomanip>
#include <iostream>
#include <locale>
#include "shade/solar_model.hpp"
#include <optional>
#include <regex>
#include <sstream>
#include <string>
#include <string_view>
#include <vector>

namespace {
using namespace std::chrono;

constexpr hours taiwanOffset{8};

struct SolarAngles {
    double azimuth;
    std::optional<double> elevation;
};

using ncu_solar::wrapPositive;

// Interpret the supplied calendar time as Taiwan time (UTC+08:00).
std::optional<sys_seconds> parseTaiwanTime(const std::string& text)
{
    static const std::regex pattern(
        R"(([0-9]{4})-([0-9]{2})-([0-9]{2}) ([0-9]{2}):([0-9]{2})(:([0-9]{2}))?)");
    std::smatch parts;
    if (!std::regex_match(text, parts, pattern)) {
        return std::nullopt;
    }

    const int yyyy = std::stoi(parts[1]);
    const unsigned mm = static_cast<unsigned>(std::stoi(parts[2]));
    const unsigned dd = static_cast<unsigned>(std::stoi(parts[3]));
    const int hour = std::stoi(parts[4]);
    const int minute = std::stoi(parts[5]);
    const int second = parts[7].matched ? std::stoi(parts[7]) : 0;
    const year_month_day date{year{yyyy}, month{mm}, day{dd}};
    if (yyyy == 0 || !date.ok() || hour > 23 || minute > 59 || second > 59) {
        return std::nullopt;
    }
    return sys_days{date} + hours{hour} + minutes{minute} + seconds{second} - taiwanOffset;
}

std::string formatTaiwanTime(sys_seconds utc)
{
    const auto localTime = utc + taiwanOffset;
    const auto midnight = floor<days>(localTime);
    const year_month_day date{midnight};
    const hh_mm_ss clock{localTime - midnight};
    std::ostringstream result;
    result << std::setfill('0') << std::setw(4) << int(date.year()) << '-'
           << std::setw(2) << unsigned(date.month()) << '-'
           << std::setw(2) << unsigned(date.day()) << 'T'
           << std::setw(2) << clock.hours().count() << ':'
           << std::setw(2) << clock.minutes().count() << ':'
           << std::setw(2) << clock.seconds().count() << "+08:00";
    return result.str();
}

void printResult(const SolarAngles& angles, std::string_view source,
                 std::optional<sys_seconds> utc = std::nullopt)
{
    std::cout << "taiwan_time,source,azimuth_deg,elevation_deg,shadow_azimuth_deg\n";
    if (utc) {
        std::cout << formatTaiwanTime(*utc);
    }
    std::cout << ',' << source << ',' << std::fixed << std::setprecision(5) << angles.azimuth << ',';
    if (angles.elevation) {
        std::cout << *angles.elevation;
    }
    std::cout << ',';
    if (angles.elevation && *angles.elevation > 0.0 && *angles.elevation < 90.0) {
        std::cout << wrapPositive(angles.azimuth + 180.0, 360.0);
    }
    std::cout << '\n';
}

void printCalculatedPosition(sys_seconds utc)
{
    const auto angles = ncu_solar::calculate(utc.time_since_epoch().count());
    printResult({angles.azimuth, angles.elevation}, "noaa_formula", utc);
}

std::optional<double> readNumber(const std::string& text)
{
    std::istringstream input(text);
    input.imbue(std::locale::classic());
    double value;
    if (!(input >> value) || !std::isfinite(value)) {
        return std::nullopt;
    }
    input >> std::ws;
    return input.eof() ? std::optional{value} : std::nullopt;
}

std::vector<std::string> readMenu()
{
    std::cout << "NCU solar position (Taiwan time, UTC+08:00)\n"
                 "1. Calculate current solar position\n"
                 "2. Enter a Taiwan date and time\n"
                 "3. Enter a solar azimuth manually\n"
                 "Choose 1, 2, or 3: ";
    std::string choice;
    std::getline(std::cin, choice);
    if (choice == "1") {
        return {"--now"};
    }
    if (choice == "2") {
        std::cout << "Taiwan date and time (YYYY-MM-DD HH:MM[:SS]): ";
        std::string time;
        std::getline(std::cin, time);
        return {"--time", time};
    }
    if (choice == "3") {
        std::string azimuth, elevation;
        std::cout << "Solar azimuth (0 to 360 degrees): ";
        std::getline(std::cin, azimuth);
        std::cout << "Solar elevation (-90 to 90 degrees, Enter to skip): ";
        std::getline(std::cin, elevation);
        if (elevation.empty()) {
            return {"--manual", azimuth};
        }
        return {"--manual", azimuth, elevation};
    }
    return {};
}
} // namespace

int main(int argc, char* argv[])
{
    const auto args = argc == 1 ? readMenu() : std::vector<std::string>(argv + 1, argv + argc);
    if (args.size() == 1 && args[0] == "--now") {
        printCalculatedPosition(floor<seconds>(system_clock::now()));
        return 0;
    }
    if (args.size() == 2 && args[0] == "--time") {
        if (const auto utc = parseTaiwanTime(args[1])) {
            printCalculatedPosition(*utc);
            return 0;
        }
        std::cerr << "Enter a valid Taiwan date and time as YYYY-MM-DD HH:MM[:SS].\n";
        return 1;
    }
    if ((args.size() == 2 || args.size() == 3) && args[0] == "--manual") {
        const auto azimuth = readNumber(args[1]);
        const auto elevation = args.size() == 3 ? readNumber(args[2]) : std::nullopt;
        if (!azimuth || *azimuth < 0.0 || *azimuth > 360.0) {
            std::cerr << "Solar azimuth must be a number from 0 to 360 degrees.\n";
            return 1;
        }
        if (args.size() == 3 && (!elevation || *elevation < -90.0 || *elevation > 90.0)) {
            std::cerr << "Solar elevation must be a number from -90 to 90 degrees.\n";
            return 1;
        }
        printResult({wrapPositive(*azimuth, 360.0), elevation}, "manual");
        return 0;
    }
    std::cerr << "Usage: solar_position_offline [--now | --time \"YYYY-MM-DD HH:MM[:SS]\""
                 " | --manual AZIMUTH [ELEVATION]]\n";
    return 1;
}
