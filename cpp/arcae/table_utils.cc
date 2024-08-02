#include "arcae/table_utils.h"

#include <string>

#include <arrow/api.h>
#include <casacore/tables/Tables/TableProxy.h>

using ::arrow::Status;
using ::casacore::TableProxy;

namespace arcae {
namespace detail {

Status ColumnExists(const TableProxy & tp, const std::string & column) {
  if(tp.table().tableDesc().isColumn(column)) return Status::OK();
  return Status::Invalid("Column ", column, " does not exist");
}

bool MaybeReopenRW(TableProxy & tp) {
  if(tp.isWritable()) return false;
  tp.reopenRW();
  return true;
}

}  // namespace detail
}  // namespace arcae
