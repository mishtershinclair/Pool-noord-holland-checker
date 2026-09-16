import requests
from bs4 import BeautifulSoup
from collections import Counter
from datetime import datetime


# ============================================================
# CONFIGURATION
# ============================================================

TOURNAMENTS = {
    "Eerste klasse": 83574424,
    "Tweede klasse": 83574427,
    "Derde klasse": 83574403,
}


# Required counts and race lengths are keyed by league, type and discipline.
# Format order does not matter.
LEAGUE_RULES = {
    "Eerste klasse": {
        ("Doubles", "10-Ball"): (1, 5),
        ("Singles", "8-Ball"): (2, 5),
        ("Singles", "Straightpool"): (1, 60),
        ("Singles", "9-Ball"): (1, 6),
        ("Singles", "10-Ball"): (1, 5),
    },
    "Tweede klasse": {
        ("Doubles", "10-Ball"): (1, 5),
        ("Singles", "8-Ball"): (2, 5),
        ("Singles", "Straightpool"): (1, 50),
        ("Singles", "9-Ball"): (1, 6),
        ("Singles", "10-Ball"): (1, 5),
    },
    "Derde klasse": {
        ("Doubles", "10-Ball"): (1, 4),
        ("Singles", "8-Ball"): (2, 4),
        ("Singles", "9-Ball"): (2, 5),
        ("Singles", "10-Ball"): (1, 5),
    },
}


DISCIPLINE_NAMES = {
    1: "7-Ball",
    2: "8-Ball",
    3: "9-Ball",
    4: "10-Ball",
    5: "Straightpool",
    6: "Onepocket",
    7: "Bankpool",
    10: "Multiball",
}


MATCH_TYPE_NAMES = {
    0: "Singles",
    2: "Doubles",
}


# ============================================================
# HELPERS
# ============================================================

def get_players(player_text):

    if not player_text:
        return []

    if player_text == "Player not selected":
        return []

    return [
        player.strip()
        for player in player_text.split(" & ")
        if player.strip()
    ]


def format_date(starttime):
    """
    Convert:
        2026-09-15T18:00:00Z

    into:
        15 September 2026
    """

    if not starttime:
        return "Unknown date"

    try:

        dt = datetime.fromisoformat(
            starttime.replace("Z", "+00:00")
        )

        return dt.strftime(
            "%d %B %Y"
        )

    except ValueError:

        return starttime


def print_fixture_header(
    league_name,
    fixture,
    individual_match_no=None
):

    print()
    print(
        f"League: {league_name}"
    )

    print(
        f"Date: {fixture['date']}"
    )

    print(
        f"Match {fixture['match_no']}"
    )

    print(
        f"{fixture['team_a']} "
        f"vs "
        f"{fixture['team_b']}"
    )

    if individual_match_no:

        print(
            f"Individual match "
            f"{individual_match_no}"
        )


# ============================================================
# CHECK ONE TOURNAMENT
# ============================================================

def check_tournament(
    league_name,
    tournament_id
):

    rules = LEAGUE_RULES[league_name]
    required_formats = Counter({key: count for key, (count, race) in rules.items()})

    print()
    print("=" * 70)
    print(
        f"CHECKING: "
        f"{league_name.upper()}"
    )
    print("=" * 70)

    print()
    print(
        "Getting CueScore tournament..."
    )


    # ========================================================
    # GET TOURNAMENT
    # ========================================================

    url = (
        "https://api.cuescore.com/"
        f"tournament/?id={tournament_id}"
    )


    try:

        response = requests.get(
            url,
            timeout=30
        )

    except requests.RequestException as error:

        print(
            f"Could not retrieve tournament: "
            f"{error}"
        )

        return {
            "league": league_name,
            "format_issues": [],
            "race_to_issues": [],
            "score_issues": [],
            "player_issues": [],
            "special_scores": [],
            "error": True,
        }


    print(
        "Status:",
        response.status_code
    )


    if response.status_code != 200:

        print(
            "Could not retrieve tournament."
        )

        return {
            "league": league_name,
            "format_issues": [],
            "race_to_issues": [],
            "score_issues": [],
            "player_issues": [],
            "special_scores": [],
            "error": True,
        }


    tournament = response.json()


    print(
        "Tournament:",
        tournament.get(
            "name",
            league_name
        )
    )


    team_matches = tournament.get(
        "matches",
        []
    )


    print(
        "Team matches found:",
        len(team_matches)
    )


    # ========================================================
    # BUILD FIXTURE INFORMATION
    # ========================================================

    fixtures = {}


    for team_match in team_matches:

        team_match_id = team_match.get(
            "matchId"
        )


        player_a_data = (
            team_match.get("playerA")
            or {}
        )

        player_b_data = (
            team_match.get("playerB")
            or {}
        )


        fixtures[team_match_id] = {

            "team_match_id":
                team_match_id,

            "match_no":
                team_match.get(
                    "matchno",
                    "?"
                ),

            "date":
                format_date(
                    team_match.get(
                        "starttime",
                        ""
                    )
                ),

            "team_a":
                player_a_data.get(
                    "name",
                    "Unknown team"
                ),

            "team_b":
                player_b_data.get(
                    "name",
                    "Unknown team"
                ),
        }


    # ========================================================
    # COLLECT INDIVIDUAL MATCHES
    # ========================================================

    print()
    print(
        "Reading individual matches..."
    )


    all_matches = []


    for team_match in team_matches:

        team_match_id = team_match[
            "matchId"
        ]


        details_url = (
            "https://cuescore.com/ajax/"
            "match/matchDetails.php"
            f"?tournamentId={tournament_id}"
            f"&id={team_match_id}"
        )


        try:

            details_response = requests.get(
                details_url,
                timeout=30
            )

        except requests.RequestException:

            print(
                f"Could not retrieve "
                f"team match "
                f"{team_match_id}"
            )

            continue


        if (
            details_response.status_code
            != 200
        ):
            continue


        soup = BeautifulSoup(
            details_response.text,
            "html.parser"
        )


        rows = soup.select(
            "tr.match.public"
        )


        for row in rows:

            row_id = row.get("id")

            if not row_id:
                continue


            individual_match_id = (
                row_id.replace(
                    "match-",
                    ""
                )
            )


            individual_match_no = (
                row.get(
                    "data-matchno",
                    ""
                )
            )


            # ================================================
            # MATCH TYPE
            # ================================================

            raw_match_type = row.get(
                "data-match-type",
                ""
            )


            try:

                raw_match_type = int(
                    raw_match_type
                )

            except (
                ValueError,
                TypeError
            ):

                raw_match_type = None


            match_type = (
                MATCH_TYPE_NAMES.get(
                    raw_match_type,
                    "Unknown"
                )
            )


            # ================================================
            # DISCIPLINE
            # ================================================

            raw_discipline = row.get(
                "data-discipline",
                ""
            )


            try:

                raw_discipline = int(
                    raw_discipline
                )

            except (
                ValueError,
                TypeError
            ):

                raw_discipline = None


            discipline = (
                DISCIPLINE_NAMES.get(
                    raw_discipline,
                    "Unknown"
                )
            )


            # ================================================
            # RACE TO
            # ================================================

            raw_race_to = row.get(
                "data-race-to",
                ""
            )


            try:

                race_to = int(
                    raw_race_to
                )

            except (
                ValueError,
                TypeError
            ):

                race_to = None


            # ================================================
            # PLAYERS
            # ================================================

            player_a_element = (
                row.select_one(
                    ".playerA .name"
                )
            )

            player_b_element = (
                row.select_one(
                    ".playerB .name"
                )
            )


            player_a = (
                player_a_element.get_text(
                    strip=True
                )
                if player_a_element
                else "Player not selected"
            )


            player_b = (
                player_b_element.get_text(
                    strip=True
                )
                if player_b_element
                else "Player not selected"
            )


            # ================================================
            # SCORES
            # ================================================

            score_a_element = (
                row.select_one(
                    ".scoreA input"
                )
            )

            score_b_element = (
                row.select_one(
                    ".scoreB input"
                )
            )


            score_a = (
                score_a_element.get(
                    "value",
                    ""
                )
                if score_a_element
                else ""
            )


            score_b = (
                score_b_element.get(
                    "value",
                    ""
                )
                if score_b_element
                else ""
            )


            # ================================================
            # STORE
            # ================================================

            all_matches.append({

                "id":
                    individual_match_id,

                "team_match_id":
                    team_match_id,

                "match_no":
                    individual_match_no,

                "type":
                    match_type,

                "discipline":
                    discipline,

                "race_to":
                    race_to,

                "player_a":
                    player_a,

                "player_b":
                    player_b,

                "score_a":
                    score_a,

                "score_b":
                    score_b,
            })


    print(
        "Individual matches found:",
        len(all_matches)
    )


    # ========================================================
    # GROUP INDIVIDUAL MATCHES
    # ========================================================

    matches_by_team = {}


    for match in all_matches:

        team_match_id = (
            match["team_match_id"]
        )


        if (
            team_match_id
            not in matches_by_team
        ):

            matches_by_team[
                team_match_id
            ] = []


        matches_by_team[
            team_match_id
        ].append(match)


    # ========================================================
    # ISSUE LISTS
    # ========================================================

    format_issues = []
    race_to_issues = []
    score_issues = []
    special_scores = []
    player_issues = []


    # ========================================================
    # FORMAT CHECK
    # ========================================================

    for (
        team_match_id,
        matches
    ) in matches_by_team.items():


        configured_matches = [
            match
            for match in matches
            if (
                match["player_a"]
                != "Player not selected"

                and

                match["player_b"]
                != "Player not selected"
            )
        ]


        # Completely untouched future match.
        if len(configured_matches) == 0:
            continue


        # Partially configured match.
        if len(configured_matches) != 6:

            format_issues.append({

                "team_match_id":
                    team_match_id,

                "fixture":
                    fixtures[
                        team_match_id
                    ],

                "message": (
                    f"Only "
                    f"{len(configured_matches)} "
                    f"of 6 individual matches "
                    f"are configured."
                ),

                "matches":
                    configured_matches,
            })

            continue


        actual_formats = Counter(
            (
                match["type"],
                match["discipline"]
            )

            for match
            in configured_matches
        )


        if (
            actual_formats
            != required_formats
        ):

            missing = (
                required_formats
                - actual_formats
            )

            unexpected = (
                actual_formats
                - required_formats
            )


            format_issues.append({

                "team_match_id":
                    team_match_id,

                "fixture":
                    fixtures[
                        team_match_id
                    ],

                "message": (
                    "The six games do not "
                    "match the required "
                    "competition format."
                ),

                "missing":
                    missing,

                "unexpected":
                    unexpected,

                "matches":
                    configured_matches,
            })


    # ========================================================
    # PLAYER PARTICIPATION CHECK
    # ========================================================

    for (
        team_match_id,
        matches
    ) in matches_by_team.items():


        configured_matches = [
            match
            for match in matches
            if (
                match["player_a"]
                != "Player not selected"

                and

                match["player_b"]
                != "Player not selected"
            )
        ]


        if len(configured_matches) != 6:
            continue


        for side in ["A", "B"]:

            player_games = {}


            for match in configured_matches:

                if side == "A":

                    player_text = (
                        match["player_a"]
                    )

                else:

                    player_text = (
                        match["player_b"]
                    )


                players = get_players(
                    player_text
                )


                for player in players:

                    if (
                        player
                        not in player_games
                    ):

                        player_games[
                            player
                        ] = []


                    player_games[
                        player
                    ].append({

                        "match_no":
                            match["match_no"],

                        "type":
                            match["type"],

                        "discipline":
                            match[
                                "discipline"
                            ],
                    })


            number_of_players = len(
                player_games
            )


            # ================================================
            # FOUR OR MORE PLAYERS
            # ================================================

            if number_of_players >= 4:

                for (
                    player,
                    games
                ) in player_games.items():


                    if len(games) > 2:

                        player_issues.append({

                            "team_match_id":
                                team_match_id,

                            "fixture":
                                fixtures[
                                    team_match_id
                                ],

                            "side":
                                side,

                            "player":
                                player,

                            "number_of_players":
                                number_of_players,

                            "games":
                                games,

                            "message": (
                                f"{player} played "
                                f"{len(games)} "
                                f"individual matches "
                                f"with "
                                f"{number_of_players} "
                                f"players used. "
                                f"Maximum allowed "
                                f"is 2."
                            )
                        })


            # ================================================
            # EXACTLY THREE PLAYERS
            # ================================================

            elif number_of_players == 3:

                players_with_three = [
                    player

                    for (
                        player,
                        games
                    )

                    in player_games.items()

                    if len(games) == 3
                ]


                # Nobody can play more than 3.

                for (
                    player,
                    games
                ) in player_games.items():


                    if len(games) > 3:

                        player_issues.append({

                            "team_match_id":
                                team_match_id,

                            "fixture":
                                fixtures[
                                    team_match_id
                                ],

                            "side":
                                side,

                            "player":
                                player,

                            "number_of_players":
                                number_of_players,

                            "games":
                                games,

                            "message": (
                                f"{player} played "
                                f"{len(games)} "
                                f"individual matches. "
                                f"With 3 players, "
                                f"maximum allowed "
                                f"is 3."
                            )
                        })


                # Only one player can play 3.

                if len(
                    players_with_three
                ) > 1:

                    player_issues.append({

                        "team_match_id":
                            team_match_id,

                        "fixture":
                            fixtures[
                                team_match_id
                            ],

                        "side":
                            side,

                        "player":
                            ", ".join(
                                players_with_three
                            ),

                        "number_of_players":
                            number_of_players,

                        "games":
                            [],

                        "message": (
                            "More than one player "
                            "played 3 individual "
                            "matches with only "
                            "3 players used."
                        )
                    })


                # Player playing 3 must
                # participate in doubles.

                for player in players_with_three:

                    games = (
                        player_games[
                            player
                        ]
                    )


                    played_doubles = any(
                        game["type"]
                        == "Doubles"

                        for game in games
                    )


                    if not played_doubles:

                        player_issues.append({

                            "team_match_id":
                                team_match_id,

                            "fixture":
                                fixtures[
                                    team_match_id
                                ],

                            "side":
                                side,

                            "player":
                                player,

                            "number_of_players":
                                number_of_players,

                            "games":
                                games,

                            "message": (
                                f"{player} played "
                                f"3 individual "
                                f"matches but did "
                                f"not participate "
                                f"in the doubles."
                            )
                        })


            # ================================================
            # FEWER THAN THREE
            # ================================================

            elif number_of_players < 3:

                player_issues.append({

                    "team_match_id":
                        team_match_id,

                    "fixture":
                        fixtures[
                            team_match_id
                        ],

                    "side":
                        side,

                    "player":
                        "",

                    "number_of_players":
                        number_of_players,

                    "games":
                        [],

                    "message": (
                        f"Only "
                        f"{number_of_players} "
                        f"players were detected. "
                        f"Check this team "
                        f"manually."
                    )
                })


    # ========================================================
    # SCORE CHECK
    # ========================================================

    for match in all_matches:


        if (
            match["player_a"]
            == "Player not selected"

            or

            match["player_b"]
            == "Player not selected"
        ):
            continue


        rule = rules.get((match["type"], match["discipline"]))
        expected_race_to = rule[1] if rule else None
        race_is_correct = rule is not None and match["race_to"] == expected_race_to
        # Check setup even when scores are blank, special, or Straightpool.
        # Unexpected formats are handled by format validation.
        if rule is not None and not race_is_correct:
            race_to_issues.append({
                "match": match,
                "fixture": fixtures[match["team_match_id"]],
                "expected_race_to": expected_race_to,
                "actual_race_to": match["race_to"],
            })

        score_a = match["score_a"]
        score_b = match["score_b"]


        if (
            score_a == ""
            or
            score_b == ""
        ):
            continue


        # Special result such as FF or WD.

        if (
            not score_a.isdigit()
            or
            not score_b.isdigit()
        ):

            special_scores.append({
                "match": match,
                "fixture": fixtures[
                    match[
                        "team_match_id"
                    ]
                ],
            })

            continue


        race_to = match["race_to"]


        if not race_is_correct:
            continue


        score_a_number = int(
            score_a
        )

        score_b_number = int(
            score_b
        )


        # Straightpool is deliberately
        # excluded from normal race-to logic.

        if (
            match["discipline"]
            == "Straightpool"
        ):
            continue


        a_won = (
            score_a_number == race_to
            and
            score_b_number < race_to
        )


        b_won = (
            score_b_number == race_to
            and
            score_a_number < race_to
        )


        if not (
            a_won
            or
            b_won
        ):

            score_issues.append({

                "match":
                    match,

                "fixture":
                    fixtures[
                        match[
                            "team_match_id"
                        ]
                    ],
            })


    # ========================================================
    # FRIENDLY REPORT
    # ========================================================

    print()
    print("-" * 70)
    print(
        f"RESULT: "
        f"{league_name.upper()}"
    )
    print("-" * 70)


    # ========================================================
    # FORMAT ISSUES
    # ========================================================

    if format_issues:

        for issue in format_issues:

            print()
            print(
                "!" * 70
            )
            print("FORMAT ISSUE")
            print(
                "!" * 70
            )


            print_fixture_header(
                league_name,
                issue["fixture"]
            )


            print()
            print(
                "Problem:",
                issue["message"]
            )


            if "missing" in issue:

                if issue["missing"]:

                    print()
                    print(
                        "Missing:"
                    )

                    for (
                        match_type,
                        discipline
                    ), count in issue[
                        "missing"
                    ].items():

                        print(
                            f"  {count} x "
                            f"{match_type} "
                            f"{discipline}"
                        )


                if issue["unexpected"]:

                    print()
                    print(
                        "Unexpected:"
                    )

                    for (
                        match_type,
                        discipline
                    ), count in issue[
                        "unexpected"
                    ].items():

                        print(
                            f"  {count} x "
                            f"{match_type} "
                            f"{discipline}"
                        )


            # If partially entered, show which
            # individual match numbers are configured.

            if issue["matches"]:

                print()
                print(
                    "Configured individual "
                    "matches:"
                )

                for match in issue[
                    "matches"
                ]:

                    print(
                        f"  Individual match "
                        f"{match['match_no']}: "
                        f"{match['type']} / "
                        f"{match['discipline']}"
                    )


    # ========================================================
    # PLAYER ISSUES
    # ========================================================

    if player_issues:

        for issue in player_issues:

            print()
            print(
                "!" * 70
            )
            print(
                "PLAYER PARTICIPATION ISSUE"
            )
            print(
                "!" * 70
            )


            print_fixture_header(
                league_name,
                issue["fixture"]
            )


            team_name = (
                issue["fixture"][
                    "team_a"
                ]

                if issue["side"] == "A"

                else issue["fixture"][
                    "team_b"
                ]
            )


            print()
            print(
                "Team:",
                team_name
            )

            print(
                "Players used:",
                issue[
                    "number_of_players"
                ]
            )


            print()
            print(
                "Problem:",
                issue["message"]
            )


            if issue["games"]:

                print()
                print(
                    "Games played by "
                    f"{issue['player']}:"
                )

                for game in issue[
                    "games"
                ]:

                    print(
                        f"  Individual match "
                        f"{game['match_no']}: "
                        f"{game['type']} / "
                        f"{game['discipline']}"
                    )


    # ========================================================
    # SCORE ISSUES
    # ========================================================

    if score_issues:

        for issue in score_issues:

            match = issue["match"]

            print()
            print(
                "!" * 70
            )
            print("SCORE ISSUE")
            print(
                "!" * 70
            )


            print_fixture_header(
                league_name,
                issue["fixture"],
                match["match_no"]
            )


            print()
            print(
                f"{match['player_a']} "
                f"{match['score_a']}-"
                f"{match['score_b']} "
                f"{match['player_b']}"
            )


            print(
                f"{match['type']} / "
                f"{match['discipline']} / "
                f"Race to "
                f"{match['race_to']}"
            )


            print()
            print(
                "Problem: Neither player "
                f"has a valid Race to "
                f"{match['race_to']} "
                f"winning score."
            )


    # ========================================================
    # RACE-TO ISSUES
    # ========================================================

    for issue in race_to_issues:
        print("RACE-TO ISSUE")
        print_fixture_header(league_name, issue["fixture"], issue["match"]["match_no"])
        print(f"Expected Race to {issue['expected_race_to']}; actual Race to {issue['actual_race_to']}")

    # ========================================================
    # SPECIAL RESULTS
    # ========================================================

    if special_scores:

        for issue in special_scores:

            match = issue["match"]

            print()
            print(
                "-" * 70
            )
            print("SPECIAL RESULT")
            print(
                "-" * 70
            )


            print_fixture_header(
                league_name,
                issue["fixture"],
                match["match_no"]
            )


            print()
            print(
                f"{match['player_a']} "
                f"{match['score_a']}-"
                f"{match['score_b']} "
                f"{match['player_b']}"
            )


            print(
                f"{match['type']} / "
                f"{match['discipline']} / "
                f"Race to "
                f"{match['race_to']}"
            )


    # ========================================================
    # LEAGUE SUMMARY
    # ========================================================

    print()
    print(
        f"Format issues: "
        f"{len(format_issues)}"
    )

    print(
        f"Score issues: "
        f"{len(score_issues)}"
    )

    print(
        f"Player participation issues: "
        f"{len(player_issues)}"
    )

    print(
        f"Special results: "
        f"{len(special_scores)}"
    )


    print(f"Race-to issues: {len(race_to_issues)}")

    return {

        "race_to_issues": race_to_issues,

        "league":
            league_name,

        "format_issues":
            format_issues,

        "score_issues":
            score_issues,

        "player_issues":
            player_issues,

        "special_scores":
            special_scores,

        "error":
            False,
    }


# ============================================================

# Console output is suppressed in the web application.
print = lambda *args, **kwargs: None
