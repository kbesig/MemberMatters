<template>
  <div>
    <div class="row justify-between items-center q-mb-md">
      <div class="text-h6">{{ $t('addons.manageAddons') }}</div>
      <q-btn
        color="primary"
        :icon="icons.add"
        :label="$t('addons.createAddon')"
        @click="openCreateDialog"
      />
    </div>

    <q-table
      :rows="addons"
      :columns="columns"
      :no-data-label="$t('addons.noAddons')"
      :loading="loading"
      row-key="id"
      :filter="filter"
      class="full-width"
    >
      <template v-slot:top-right>
        <q-input
          v-model="filter"
          outlined
          dense
          debounce="300"
          placeholder="Search"
        >
          <template v-slot:append>
            <q-icon :name="icons.search" />
          </template>
        </q-input>
      </template>

      <template v-slot:body-cell-stripeSynced="props">
        <q-td :props="props">
          <q-icon
            :name="
              props.row.stripe_synced ? 'mdi-check-circle' : 'mdi-alert-circle'
            "
            :color="props.row.stripe_synced ? 'positive' : 'warning'"
          />
        </q-td>
      </template>

      <template v-slot:body-cell-actions="props">
        <q-td :props="props">
          <q-btn
            flat
            round
            dense
            :icon="icons.edit"
            @click.stop="openEditDialog(props.row)"
          />
          <q-btn
            flat
            round
            dense
            color="negative"
            :icon="icons.delete"
            @click.stop="deleteAddon(props.row)"
          />
        </q-td>
      </template>
    </q-table>

    <!-- Create/Edit dialog -->
    <q-dialog v-model="showDialog">
      <q-card style="min-width: 400px">
        <q-card-section class="row items-center q-pb-none">
          <div class="text-h6">
            {{
              editingAddon ? $t('addons.editAddon') : $t('addons.createAddon')
            }}
          </div>
          <q-space />
          <q-btn icon="mdi-close" flat round dense v-close-popup />
        </q-card-section>

        <q-card-section class="q-gutter-sm">
          <q-input
            v-model="form.name"
            :label="$t('addons.name')"
            outlined
            dense
          />
          <q-input
            v-model="form.description"
            :label="$t('addons.description')"
            outlined
            dense
          />
          <q-select
            v-model="form.addon_type"
            :label="$t('addons.addonType')"
            :options="addonTypeOptions"
            outlined
            dense
            emit-value
            map-options
          />
          <q-input
            v-model.number="form.cost"
            :label="$t('addons.cost')"
            outlined
            dense
            type="number"
          />
          <q-input
            v-model="form.currency"
            :label="$t('addons.currency')"
            outlined
            dense
          />
          <q-select
            v-model="form.interval"
            :label="$t('addons.interval')"
            :options="intervalOptions"
            outlined
            dense
            emit-value
            map-options
          />
          <q-input
            v-model.number="form.interval_count"
            :label="$t('addons.intervalCount')"
            outlined
            dense
            type="number"
          />
          <q-input
            v-model.number="form.min_quantity"
            :label="$t('addons.minQuantity')"
            outlined
            dense
            type="number"
          />
          <q-input
            v-model.number="form.max_quantity"
            :label="$t('addons.maxQuantity')"
            outlined
            dense
            type="number"
          />
          <q-toggle v-model="form.visible" :label="$t('addons.visible')" />
        </q-card-section>

        <q-card-actions align="right">
          <q-btn flat :label="$t('button.cancel')" v-close-popup />
          <q-btn
            color="primary"
            :label="editingAddon ? $t('button.save') : $t('addons.createAddon')"
            :loading="loadingSave"
            :disable="!form.name || !form.addon_type"
            @click="saveAddon"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </div>
</template>

<script lang="ts">
import icons from '@icons';

const defaultForm = () => ({
  name: '',
  description: '',
  addon_type: 'custom',
  cost: 0,
  currency: 'aud',
  interval: 'month',
  interval_count: 1,
  min_quantity: 1,
  max_quantity: 10,
  visible: true,
});

export default {
  name: 'AdminAddonManager',
  data() {
    return {
      loading: true,
      filter: '',
      addons: [] as {
        id: number;
        name: string;
        description: string;
        addon_type: string;
        addon_type_display: string;
        visible: boolean;
        currency: string;
        cost: number;
        cost_display: string;
        interval_count: number;
        interval: string;
        stripe_synced: boolean;
      }[],
      showDialog: false,
      editingAddon: null as null | (typeof this.addons)[0],
      form: defaultForm(),
      loadingSave: false,
    };
  },
  computed: {
    icons() {
      return icons;
    },
    columns() {
      return [
        {
          name: 'name',
          label: this.$t('addons.name'),
          field: 'name',
          sortable: true,
          align: 'left',
        },
        {
          name: 'addon_type',
          label: this.$t('addons.addonType'),
          field: 'addon_type_display',
          sortable: true,
          align: 'left',
        },
        {
          name: 'cost',
          label: this.$t('addons.cost'),
          field: 'cost_display',
          sortable: true,
          align: 'left',
        },
        {
          name: 'interval',
          label: this.$t('addons.interval'),
          field: (row: (typeof this.addons)[0]) =>
            `${row.interval_count} ${row.interval}`,
          align: 'left',
        },
        {
          name: 'stripeSynced',
          label: this.$t('addons.stripeSynced'),
          field: 'stripe_synced',
          align: 'center',
        },
        { name: 'actions', label: '', field: 'actions', align: 'right' },
      ];
    },
    addonTypeOptions() {
      return [
        { label: 'Additional Member', value: 'additional_member' },
        { label: 'Storage Upgrade', value: 'storage_upgrade' },
        { label: 'Priority Support', value: 'priority_support' },
        { label: 'Equipment Rental', value: 'equipment_rental' },
        { label: 'Shelf Rental', value: 'shelf_rental' },
        { label: 'Custom', value: 'custom' },
      ];
    },
    intervalOptions() {
      return [
        { label: 'Month', value: 'month' },
        { label: 'Week', value: 'week' },
        { label: 'Day', value: 'day' },
      ];
    },
  },
  async mounted() {
    await this.fetchAddons();
  },
  methods: {
    async fetchAddons() {
      this.loading = true;
      try {
        const result = await this.$axios.get('/api/admin/addons/');
        this.addons = Array.isArray(result.data) ? result.data : [];
      } catch {
        this.addons = [];
      } finally {
        this.loading = false;
      }
    },
    openCreateDialog() {
      this.editingAddon = null;
      this.form = defaultForm();
      this.showDialog = true;
    },
    openEditDialog(addon: (typeof this.addons)[0]) {
      this.editingAddon = addon;
      this.form = {
        name: addon.name,
        description: addon.description,
        addon_type: addon.addon_type,
        cost: addon.cost,
        currency: addon.currency,
        interval: addon.interval,
        interval_count: addon.interval_count,
        min_quantity: addon.min_quantity,
        max_quantity: addon.max_quantity,
        visible: addon.visible,
      };
      this.showDialog = true;
    },
    async saveAddon() {
      this.loadingSave = true;
      try {
        let result;
        if (this.editingAddon) {
          result = await this.$axios.put(
            `/api/admin/addons/${this.editingAddon.id}/`,
            this.form
          );
          this.$q.notify({
            type: 'positive',
            message: this.$t('addons.updateSuccess'),
          });
        } else {
          result = await this.$axios.post('/api/admin/addons/', this.form);
          this.$q.notify({
            type: 'positive',
            message: this.$t('addons.createSuccess'),
          });
        }
        if (result.data) {
          this.showDialog = false;
          await this.fetchAddons();
        }
      } catch {
        this.$q.notify({
          type: 'negative',
          message: this.editingAddon
            ? this.$t('addons.updateFailed')
            : this.$t('addons.createFailed'),
        });
      } finally {
        this.loadingSave = false;
      }
    },
    deleteAddon(addon: (typeof this.addons)[0]) {
      this.$q
        .dialog({
          title: this.$t('addons.deleteAddon'),
          message: this.$t('addons.deleteAddonConfirm'),
          cancel: this.$t('button.cancel'),
          persistent: true,
        })
        .onOk(async () => {
          try {
            await this.$axios.delete(`/api/admin/addons/${addon.id}/`);
            this.$q.notify({
              type: 'positive',
              message: this.$t('addons.deleteSuccess'),
            });
            await this.fetchAddons();
          } catch {
            this.$q.notify({
              type: 'negative',
              message: this.$t('addons.deleteFailed'),
            });
          }
        });
    },
  },
};
</script>
