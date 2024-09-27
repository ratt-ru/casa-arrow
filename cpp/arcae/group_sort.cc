#include "group_sort.h"

#include <algorithm>
#include <cstdint>
#include <memory>
#include <numeric>
#include <queue>
#include <vector>

#include "arcae/type_traits.h"

#include "arrow/api.h"
#include "arrow/buffer.h"
#include "arrow/result.h"
#include "arrow/status.h"
#include "arrow/type_fwd.h"

using ::arrow::AllocateBuffer;
using ::arrow::Array;
using ::arrow::Buffer;
using ::arrow::DoubleArray;
using ::arrow::Int32Array;
using ::arrow::Int64Array;
using ::arrow::Result;
using ::arrow::Status;

using ::arcae::detail::AggregateAdapter;

namespace arcae {

namespace {

static constexpr char kArrayIsNull[] = "GroupSortData array is null";
static constexpr char kLengthMismatch[] = "GroupSortData length mismatch";
static constexpr char kHasNulls[] = "GroupSortData has nulls";

}  // namespace

Result<std::shared_ptr<GroupSortData>> GroupSortData::Make(
    const std::vector<std::shared_ptr<Array>>& groups, const std::shared_ptr<Array>& time,
    const std::shared_ptr<Array>& ant1, const std::shared_ptr<Array>& ant2,
    const std::shared_ptr<Array>& rows) {
  if (time == nullptr || ant1 == nullptr || ant2 == nullptr || rows == nullptr)
    return Status::Invalid(kArrayIsNull);
  if (time->length() != ant1->length() || time->length() != ant2->length() ||
      time->length() != rows->length())
    return Status::Invalid(kLengthMismatch);

  if (time->type() != arrow::float64())
    return Status::Invalid("time column was not float64");
  if (ant1->type() != arrow::int32()) return Status::Invalid("ant1 column was not int32");
  if (ant2->type() != arrow::int32()) return Status::Invalid("ant2 column was not int32");
  if (rows->type() != arrow::int64()) return Status::Invalid("row column was not int64");

  if (time->data()->MayHaveNulls()) return Status::Invalid(kHasNulls);
  if (ant1->data()->MayHaveNulls()) return Status::Invalid(kHasNulls);
  if (ant2->data()->MayHaveNulls()) return Status::Invalid(kHasNulls);
  if (rows->data()->MayHaveNulls()) return Status::Invalid(kHasNulls);

  std::vector<std::shared_ptr<Int32Array>> groups_int32;
  groups_int32.reserve(groups.size());

  for (const auto& group : groups) {
    if (group == nullptr) return Status::Invalid(kArrayIsNull);
    if (time->length() != group->length()) return Status::Invalid(kLengthMismatch);
    if (group->type() != arrow::int32())
      return Status::Invalid("Grouping column was not int32");
    if (group->data()->MayHaveNulls()) return Status::Invalid(kHasNulls);
    groups_int32.push_back(std::dynamic_pointer_cast<arrow::Int32Array>(group));
  }

  return std::make_shared<AggregateAdapter<GroupSortData>>(
      std::move(groups_int32), std::dynamic_pointer_cast<DoubleArray>(time),
      std::dynamic_pointer_cast<Int32Array>(ant1),
      std::dynamic_pointer_cast<Int32Array>(ant2),
      std::dynamic_pointer_cast<Int64Array>(rows));
}

Result<std::shared_ptr<GroupSortData>> GroupSortData::Sort() const {
  std::vector<const int*> groups;
  groups.reserve(groups_.size());
  for (const auto& g : groups_) groups.push_back(g->raw_values());
  auto time = time_->raw_values();
  auto ant1 = ant1_->raw_values();
  auto ant2 = ant2_->raw_values();
  auto rows = rows_->raw_values();
  auto nrow = time_->length();

  // Generate sort indices
  std::vector<int64_t> index(nrow);
  std::iota(std::begin(index), std::end(index), 0);
  std::sort(std::begin(index), std::end(index), [&](std::int64_t l, std::int64_t r) {
    for (std::size_t i = 0; i < groups.size(); ++i) {
      if (groups[i][l] != groups[i][r]) {
        return groups[i][l] < groups[i][r];
      }
    }
    if (time[l] != time[r]) return time[l] < time[r];
    if (ant1[l] != ant1[r]) return ant1[l] < ant1[r];
    return ant2[l] < ant2[r];
  });

  // Allocate output buffers
  std::vector<std::shared_ptr<Buffer>> group_buffers(groups.size());
  std::vector<std::shared_ptr<Int32Array>> group_arrays(groups.size());
  std::vector<arrow::util::span<std::int32_t>> group_spans(groups.size());
  for (std::size_t g = 0; g < groups.size(); ++g) {
    ARROW_ASSIGN_OR_RAISE(group_buffers[g], AllocateBuffer(nrow * sizeof(std::int32_t)));
    group_arrays[g] = std::make_shared<Int32Array>(nrow, group_buffers[g]);
    group_spans[g] = group_buffers[g]->mutable_span_as<std::int32_t>();
  }

  ARROW_ASSIGN_OR_RAISE(std::shared_ptr<Buffer> time_buffer,
                        AllocateBuffer(nrow * sizeof(double)));
  ARROW_ASSIGN_OR_RAISE(std::shared_ptr<Buffer> ant1_buffer,
                        AllocateBuffer(nrow * sizeof(std::int32_t)));
  ARROW_ASSIGN_OR_RAISE(std::shared_ptr<Buffer> ant2_buffer,
                        AllocateBuffer(nrow * sizeof(std::int32_t)));
  ARROW_ASSIGN_OR_RAISE(std::shared_ptr<Buffer> rows_buffer,
                        AllocateBuffer(nrow * sizeof(std::int64_t)));

  auto time_span = time_buffer->mutable_span_as<double>();
  auto ant1_span = ant1_buffer->mutable_span_as<std::int32_t>();
  auto ant2_span = ant2_buffer->mutable_span_as<std::int32_t>();
  auto rows_span = rows_buffer->mutable_span_as<std::int64_t>();

  auto DoCopy = [&index, &nrow](auto out, auto in) {
    for (std::int64_t r = 0; r < nrow; ++r) out[r] = in[index[r]];
  };

  for (std::size_t g = 0; g < groups.size(); ++g) DoCopy(group_spans[g], groups[g]);
  DoCopy(time_span, time);
  DoCopy(ant1_span, ant1);
  DoCopy(ant2_span, ant2);
  DoCopy(rows_span, rows);

  return std::make_shared<AggregateAdapter<GroupSortData>>(
      std::move(group_arrays),
      std::make_shared<DoubleArray>(nrow, std::move(time_buffer)),
      std::make_shared<Int32Array>(nrow, std::move(ant1_buffer)),
      std::make_shared<Int32Array>(nrow, std::move(ant2_buffer)),
      std::make_shared<Int64Array>(nrow, std::move(rows_buffer)));
}

Result<std::shared_ptr<GroupSortData>> MergeGroups(
    const std::vector<std::shared_ptr<GroupSortData>>& group_data) {
  if (group_data.empty())
    return std::make_shared<AggregateAdapter<GroupSortData>>(
        GroupSortData::GroupsType{}, nullptr, nullptr, nullptr, nullptr);

  struct MergeData {
    std::size_t gd;
    GroupSortData* group;
    std::int64_t r;

    double time(std::int64_t r) const { return group->time()[r]; }
    std::int32_t ant1(std::int64_t r) const { return group->ant1()[r]; }
    std::int32_t ant2(std::int64_t r) const { return group->ant2()[r]; }

    bool operator<(const MergeData& rhs) const {
      // To obtain a descending sort, we reverse the comparison
      for (std::size_t g = 0; g < group->nGroups(); ++g) {
        auto lhs_group = group->group(g)[r];
        auto rhs_group = rhs.group->group(g)[rhs.r];
        if (lhs_group != rhs_group) return lhs_group > rhs_group;
      }
      if (time(r) != rhs.time(rhs.r)) return time(r) > rhs.time(rhs.r);
      if (ant1(r) != rhs.ant1(rhs.r)) return ant1(r) > rhs.ant1(rhs.r);
      return ant2(r) > rhs.ant2(rhs.r);
    }
  };

  std::int64_t nrows = 0;
  // TOOD: Check for consistency across data here
  auto ngroups = group_data[0]->nGroups();
  for (const auto& g : group_data) nrows += g->nRows();

  std::vector<std::shared_ptr<Buffer>> group_buffers(ngroups);
  std::vector<std::shared_ptr<Int32Array>> group_arrays(ngroups);
  std::vector<arrow::util::span<std::int32_t>> group_spans(ngroups);

  for (std::size_t g = 0; g < ngroups; ++g) {
    ARROW_ASSIGN_OR_RAISE(group_buffers[g], AllocateBuffer(nrows * sizeof(std::int32_t)));
    group_spans[g] = group_buffers[g]->mutable_span_as<std::int32_t>();
    group_arrays[g] = std::make_shared<Int32Array>(nrows, group_buffers[g]);
  }

  ARROW_ASSIGN_OR_RAISE(std::shared_ptr<Buffer> time_buffer,
                        AllocateBuffer(nrows * sizeof(double)));
  ARROW_ASSIGN_OR_RAISE(std::shared_ptr<Buffer> ant1_buffer,
                        AllocateBuffer(nrows * sizeof(std::int32_t)));
  ARROW_ASSIGN_OR_RAISE(std::shared_ptr<Buffer> ant2_buffer,
                        AllocateBuffer(nrows * sizeof(std::int32_t)));
  ARROW_ASSIGN_OR_RAISE(std::shared_ptr<Buffer> rows_buffer,
                        AllocateBuffer(nrows * sizeof(std::int64_t)));

  auto time_span = time_buffer->mutable_span_as<double>();
  auto ant1_span = ant1_buffer->mutable_span_as<std::int32_t>();
  auto ant2_span = ant2_buffer->mutable_span_as<std::int32_t>();
  auto rows_span = rows_buffer->mutable_span_as<std::int64_t>();

  std::int64_t row = 0;
  std::priority_queue<MergeData> queue;

  for (std::size_t gd = 0; gd < group_data.size(); ++gd) {
    if (group_data[gd]->nRows() > 0) {
      queue.emplace(MergeData{gd, group_data[gd].get(), 0});
    }
  }

  while (!queue.empty()) {
    auto [gd, dummy, gr] = queue.top();
    const auto& top_group = group_data[gd];
    queue.pop();

    for (std::size_t g = 0; g < ngroups; ++g) {
      group_spans[g][row] = top_group->group(g)[gr];
    }

    time_span[row] = top_group->time()[gr];
    ant1_span[row] = top_group->ant1()[gr];
    ant2_span[row] = top_group->ant2()[gr];
    rows_span[row] = top_group->rows()[gr];
    ++row;

    if (gr + 1 < top_group->nRows()) {
      queue.emplace(MergeData{gd, top_group.get(), gr + 1});
    }
  }

  return std::make_shared<AggregateAdapter<GroupSortData>>(
      std::move(group_arrays),
      std::make_shared<DoubleArray>(nrows, std::move(time_buffer)),
      std::make_shared<Int32Array>(nrows, std::move(ant1_buffer)),
      std::make_shared<Int32Array>(nrows, std::move(ant2_buffer)),
      std::make_shared<Int64Array>(nrows, std::move(rows_buffer)));
}

}  // namespace arcae