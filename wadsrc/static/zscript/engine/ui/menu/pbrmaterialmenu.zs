class PBRMaterialMenu : OptionMenu
{
	static native bool PickAimedMaterial();
	static native bool SelectMaterial(String texture);
	static native String GetMaterialLabel();
	static native double GetParameter(int parameter);
	static native void SetParameter(int parameter, double value);
	static native bool HasRelief();
	static native bool SaveOverrides();
	static native void ResetOverrides();
	static native void DiscardPreview();

	override void Init(Menu parent, OptionMenuDescriptor desc)
	{
		Super.Init(parent, desc);
		RefreshMaterial();
	}

	override void OnDestroy()
	{
		DiscardPreview();
		Super.OnDestroy();
	}

	void SetStatus(String message)
	{
		let item = GetItem('PBRMaterialStatus');
		if (item == null) return;
		item.SetString(0, message);
		item.SetValue(0, message.Length() > 0 ? 1 : 0);
	}

	void RefreshMaterial()
	{
		String label = GetMaterialLabel();
		let item = GetItem('PBRMaterialName');
		if (item != null)
		{
			item.SetString(0, label);
			item.SetValue(0, label.Length() > 0 ? 1 : 0);
		}
		if (mDesc.mSelectedItem >= 0 && !mDesc.mItems[mDesc.mSelectedItem].Selectable())
			mDesc.mSelectedItem = FirstSelectable();
		if (label.Length() > 0 && !HasRelief())
			SetStatus("This material has no relief map.");
		else
			SetStatus("");
	}
}

class OptionMenuItemPBRMaterialSlider : OptionMenuSliderBase
{
	private int parameter;

	OptionMenuItemPBRMaterialSlider Init(String label, int param, double minval, double maxval)
	{
		Super.Init(label, minval, maxval, 0.05, 2);
		parameter = param;
		return self;
	}

	override bool IsGrayed()
	{
		return PBRMaterialMenu.GetMaterialLabel().Length() == 0 ||
			(parameter == 4 && !PBRMaterialMenu.HasRelief());
	}

	override double GetSliderValue()
	{
		return PBRMaterialMenu.GetParameter(parameter);
	}

	override void SetSliderValue(double value)
	{
		let menu = PBRMaterialMenu(Menu.GetCurrentMenu());
		if (menu == null || IsGrayed()) return;
		PBRMaterialMenu.SetParameter(parameter, value);
		menu.SetStatus("Previewing unsaved changes");
	}
}

class OptionMenuItemPBRMaterialAction : OptionMenuItem
{
	enum PBRMenuAction
	{
		PickMaterial,
		SaveMaterial,
		PreviewDefaults
	}

	private int operation;

	OptionMenuItemPBRMaterialAction Init(String label, int itemOperation)
	{
		Super.Init(label, 'None');
		operation = itemOperation;
		return self;
	}

	override bool Selectable()
	{
		return operation == PickMaterial || PBRMaterialMenu.GetMaterialLabel().Length() > 0;
	}

	override int Draw(OptionMenuDescriptor desc, int y, int indent, bool selected)
	{
		drawLabel(indent, y, selected ? OptionMenuSettings.mFontColorSelection : OptionMenuSettings.mFontColorMore,
			!Selectable());
		return indent;
	}

	override bool Activate()
	{
		let menu = PBRMaterialMenu(Menu.GetCurrentMenu());
		if (menu == null || !Selectable()) return false;

		Menu.MenuSound("menu/choose");
		switch (operation)
		{
		case PickMaterial:
			if (PBRMaterialMenu.PickAimedMaterial())
				menu.RefreshMaterial();
			else
				menu.SetStatus("Aim at a surface with a PBR material.");
			break;
		case SaveMaterial:
			if (PBRMaterialMenu.SaveOverrides())
				menu.SetStatus("Material settings saved.");
			else
				menu.SetStatus("Could not save material settings.");
			break;
		case PreviewDefaults:
			PBRMaterialMenu.ResetOverrides();
			menu.SetStatus("Defaults previewed. Select Save to keep them.");
			break;
		}
		return true;
	}
}

class OptionMenuItemPBRMaterialLookup : OptionMenuItemTextField
{
	OptionMenuItemPBRMaterialLookup Init(String label)
	{
		Super.Init(label, 'None');
		return self;
	}

	override bool, String GetString(int index)
	{
		return index == 0, "";
	}

	override bool SetString(int index, String texture)
	{
		// TextEnterMenu may still be active when it calls the parent.
		let active = Menu.GetCurrentMenu();
		let menu = PBRMaterialMenu(active);
		if (menu == null && active != null)
			menu = PBRMaterialMenu(active.mParentMenu);
		if (index != 0 || menu == null) return false;

		if (PBRMaterialMenu.SelectMaterial(texture))
			menu.RefreshMaterial();
		else
			menu.SetStatus("No PBR material matches that name.");
		return true;
	}
}
