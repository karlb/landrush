-- name: create-schema#
CREATE TABLE game(
    game_id INT NOT NULL PRIMARY KEY,
    state PICKLE NOT NULL,
    number_of_players INT NOT NULL,
    max_time FLOAT NOT NULL,
    auction_size INT NOT NULL,
    start_money INT NOT NULL,
    new_money INT NOT NULL,
    final_payout INT NOT NULL,
    auction_type TEXT NOT NULL,
    name TEXT NOT NULL,
    version INT NOT NULL,
    created_at INT NOT NULL,
    finished_at INT,
    status TEXT NOT NULL,
    turn INT NOT NULL,
    auction_order TEXT NOT NULL,
    next_auction_time INT,
    payout_exponent FLOAT NOT NULL,
    allowed_missed_deadlines INT NOT NULL,
    public BOOL NOT NULL
);


-- name: save_game!
INSERT OR REPLACE INTO game(
    game_id, state, number_of_players, max_time, auction_size, start_money,
    new_money, final_payout, auction_type, name, version, created_at,
    finished_at, status, turn, auction_order, next_auction_time,
    payout_exponent, allowed_missed_deadlines, public
)
VALUES(
    :game_id, :state, :number_of_players, :max_time, :auction_size, :start_money,
    :new_money, :final_payout, :auction_type, :name, :version, :created_at,
    :finished_at, :status, :turn, :auction_order, :next_auction_time,
    :payout_exponent, :allowed_missed_deadlines, :public
)


-- name: get_game^
-- record_class: game
SELECT *
FROM game
WHERE game_id = :game_id


-- name: get_open_games
-- record_class: game
SELECT *
FROM game
WHERE public
  AND status = 'new'
  AND created_at BETWEEN strftime('%s', 'now') - 30 * 24 * 60 * 60 AND strftime('%s', 'now')  -- last 30 days


-- name: get_games_by_status
-- record_class: game
SELECT *
FROM game
WHERE public
  AND status = :status
ORDER BY finished_at DESC, created_at DESC
LIMIT :limit
